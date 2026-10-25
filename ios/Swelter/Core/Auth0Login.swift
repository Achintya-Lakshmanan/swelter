import AuthenticationServices
import CryptoKit
import Foundation
import UIKit

/// Auth0 Universal Login with PKCE, using the system web sheet (no SDK). The tenant settings come from the
/// server's /api/config so the app and the API always agree on domain, client and audience.
@MainActor
final class Auth0Login: NSObject, ASWebAuthenticationPresentationContextProviding {
    struct Session { let accessToken: String; let name: String? }

    static let scheme = "app.swelter.Swelter"

    func signIn(domain: String, clientId: String, audience: String?) async throws -> Session {
        let verifier = Self.random(32)
        let challenge = Data(SHA256.hash(data: Data(verifier.utf8))).base64url
        let state = Self.random(16)
        let redirect = "\(Self.scheme)://\(domain)/ios/\(Self.scheme)/callback"
        var c = URLComponents(string: "https://\(domain)/authorize")!
        c.queryItems = [
            .init(name: "response_type", value: "code"), .init(name: "client_id", value: clientId),
            .init(name: "redirect_uri", value: redirect), .init(name: "scope", value: "openid profile email"),
            .init(name: "code_challenge", value: challenge), .init(name: "code_challenge_method", value: "S256"),
            .init(name: "state", value: state),
            .init(name: "prompt", value: "login"),  // always ask, so a shared demo phone can switch accounts
        ] + (audience.map { [.init(name: "audience", value: $0)] } ?? [])

        let callback: URL = try await withCheckedThrowingContinuation { cont in
            let s = ASWebAuthenticationSession(url: c.url!, callbackURLScheme: Self.scheme) { url, err in
                if let url { cont.resume(returning: url) } else { cont.resume(throwing: err ?? APIError(message: "Sign-in cancelled")) }
            }
            s.presentationContextProvider = self
            s.start()
        }
        let q = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        if let e = q.first(where: { $0.name == "error_description" })?.value { throw APIError(message: e) }
        guard q.first(where: { $0.name == "state" })?.value == state, let code = q.first(where: { $0.name == "code" })?.value else {
            throw APIError(message: "Sign-in response didn't match")
        }

        var r = URLRequest(url: URL(string: "https://\(domain)/oauth/token")!)
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: [
            "grant_type": "authorization_code", "client_id": clientId, "code_verifier": verifier,
            "code": code, "redirect_uri": redirect,
        ])
        let (data, _) = try await URLSession.shared.data(for: r)
        let tok = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        guard let access = tok["access_token"] as? String else {
            throw APIError(message: tok["error_description"] as? String ?? "Auth0 didn't return a token")
        }
        let claims = (tok["id_token"] as? String).flatMap(Self.claims) ?? [:]
        let name = claims["name"] as? String ?? claims["nickname"] as? String
        return Session(accessToken: access, name: name)
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.keyWindow }.first ?? ASPresentationAnchor()
    }

    private static func random(_ n: Int) -> String {
        var b = [UInt8](repeating: 0, count: n)
        _ = SecRandomCopyBytes(kSecRandomDefault, n, &b)
        return Data(b).base64url
    }

    private static func claims(_ jwt: String) -> [String: Any]? {
        let parts = jwt.split(separator: ".")
        guard parts.count > 1 else { return nil }
        var s = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        s += String(repeating: "=", count: (4 - s.count % 4) % 4)
        return Data(base64Encoded: s).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
    }
}

/// The Auth0 access token is kept in the Keychain so the app stays signed in across launches.
enum Keychain {
    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "app.swelter.Swelter", kSecAttrAccount as String: key]
    }

    static func get(_ key: String) -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func set(_ value: String?, _ key: String) {
        SecItemDelete(query(key) as CFDictionary)
        guard let value else { return }
        var q = query(key)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        SecItemAdd(q as CFDictionary, nil)
    }
}

private extension Data {
    var base64url: String {
        base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
