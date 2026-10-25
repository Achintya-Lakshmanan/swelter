import CoreLocation
import Foundation

// MARK: - What the server sends (backend/api.py)

struct AppConfig: Decodable {
    struct Auth0: Decodable { let enabled: Bool; let domain: String?; let clientId: String?; let audience: String?; let demoAccounts: [DemoAccount] }
    struct DemoAccount: Decodable, Identifiable { let id: String; let role: String; let name: String; let about: String }
    let auth0: Auth0
    let voice: Bool
    let db: String
    let kMin: Int
    let replayDays: [String: String]
}

struct Conditions: Decodable {
    // live (NWS KPHL + Open-Meteo)
    var observedAt: String?; var station: String?; var tempF: Int?; var heatIndexF: Int?; var windChillF: Int?
    var humidity: Int?; var summary: String?; var aqi: Int?; var aqiSource: String?
    // replay of a recorded day
    var label: String?; var day: String?; var value: Double?; var unit: String?; var hour: Int?; var note: String?
    var source: String?; var simulated: Bool?
}

struct NWSAlert: Decodable, Identifiable {
    var id: String { event + (ends ?? "") }
    let event: String; let headline: String?; let severity: String?; let ends: String?
    let description: String; let instruction: String; let hazard: String?
}

struct Hourly: Decodable { let time: String; let tempF: Int; let short: String }

struct MatchedDay: Decodable { let scenario: String; let day: String; let peak: Double; let unit: String; let source: String }

struct Live: Decodable {
    struct Simulated: Decodable { let date: String; let label: String }
    let mode: String
    let hazard: String?
    let replay: Bool
    let matchedDay: MatchedDay?
    let conditions: Conditions
    let alerts: [NWSAlert]
    let forecast: [Hourly]
    var note: String?
    /// During a replay: the date the demo pretends it is (the record day, this year).
    var simulated: Simulated?
    /// Danger level of the current reading, with the simulator's bands (0 safe … 3 extreme).
    var danger: Danger?
}

struct Danger: Decodable {
    let level: Int; let vulnerableLevel: Int; let words: String; let vulnerableWords: String
    let hazard: String; let value: Double
}

struct Crowd: Decodable {
    let level: String?
    let source: String
    var minutesAgo: Int?; var phonesInside: Int?; var phones4h: Int?
    var busiestHour: Int?; var byHour: [Int]?; var hours: [Int]?; var realDay: String?; var note: String?

    var sourceText: String {
        switch source {
        case "site lead": "Site lead, \(minutesAgo ?? 0) min ago"
        case "phones": "\(phones4h ?? 0) phones in the last 4 hours"
        case "swelter forecast": "Swelter forecast (simulated, \(realDay ?? "a real day"))"
        default: "No reports yet"
        }
    }

    /// The simulation covers 6 AM-10 PM; overnight a forecast site has no level rather than another hour's.
    var levelText: String {
        level == nil && source == "swelter forecast" ? "No forecast this hour" : LevelStyle.of(level).label
    }
}

struct Site: Decodable, Identifiable, Hashable {
    static func == (a: Site, b: Site) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }

    let id: String; let name: String; let type: String; let address: String; let lat: Double; let lon: Double
    let hoursText: String?; let status: String?; let cooling: Bool?; let warming: Bool?
    let openNow: Bool; let closes: String?; let capacity: Int?; let accessible: Bool?; let water: Bool?
    let services: String?; let facilities: String?; let source: String
    let crowd: Crowd

    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lon) }
    var location: CLLocation { .init(latitude: lat, longitude: lon) }
    var hoursLine: String {
        guard openNow else { return status == "open" ? "Closed now" : "Not open this season" }
        guard let c = closes else { return "Open now" }
        return c == "open 24 hours" ? "Open 24 hours" : "Open until \(c)"
    }
    /// A phone number if the city's free-text services field has one.
    var phone: String? {
        guard let s = services, let r = s.range(of: #"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}"#, options: .regularExpression) else { return nil }
        return String(s[r])
    }
}

struct SitesResponse: Decodable {
    struct Counts: Decodable { let total: Int; let openNow: Int }
    let mode: String; let scenario: String?; let replay: Bool; let kMin: Int; let sites: [Site]; let counts: Counts
}

struct HelpRequest: Decodable, Identifiable, Hashable {
    static func == (a: HelpRequest, b: HelpRequest) -> Bool { a.id == b.id && a.status == b.status && a.exact == b.exact }
    func hash(into h: inout Hasher) { h.combine(id) }
    let id: String; let created: Int; let need: String; let flags: [String]; let people: Int?; let status: String
    let claimedName: String?; let claimedAt: Int?; let closedAt: Int?; let outcome: String?
    // responder view only
    var mine: Bool?; var minutesWaiting: Int?; var lat: Double?; var lon: Double?; var exact: Bool?
    var callback: String?; var note: String?; var name: String?

    var coordinate: CLLocationCoordinate2D? { lat.flatMap { la in lon.map { .init(latitude: la, longitude: $0) } } }
    /// Waiting time plus 15 minutes for each risk factor: the queue's "most urgent first".
    var urgency: Int { (minutesWaiting ?? 0) + 15 * flags.filter { HelpRequest.riskFlags.contains($0) }.count }
    static let riskFlags: Set = ["older", "alone", "noac", "noheat", "medical", "mobility"]
}

struct Created: Decodable { let id: String; let secret: String }

/// The signed-in person (GET /api/me). Responders are made by an organiser in Auth0, never by the app.
struct Me: Decodable {
    struct Home: Codable { let name: String?; let lat: Double; let lon: Double }
    struct Profile: Decodable { let name: String; let phone: String?; let flags: [String]; let home: Home? }
    let sub: String; let role: String; let demo: Bool; let profile: Profile?
    var name: String?
    var isResponder: Bool { role == "responder" }
    var isGovernment: Bool { role == "government" }
}

struct RiskGrid: Decodable {
    struct Cell: Decodable { let lat: Double; let lon: Double; let danger: Int; let people: Int }
    let scenario: String?; let hour: Int?; let simulated: Bool?; let step: Double?; let cells: [Cell]; let unit: String?; let realDay: String?
    let note: String
}

struct QueueResponse: Decodable { let requests: [HelpRequest]; let you: String }

// MARK: - Labels shared by both modes

enum Labels {
    static let needs: [(id: String, label: String, sub: String)] = [
        ("ride", "A ride to a cool or warm place", "Too far or too risky to walk"),
        ("water", "Water or supplies", "Brought to you"),
        ("check", "Check on someone", "Me, or a neighbour"),
        ("stuck", "I can't get out", "Flooding, snow, stairs"),
    ]
    static let flags: [(id: String, label: String)] = [
        ("older", "65 or older"), ("alone", "Lives alone"), ("noac", "No AC at home"), ("noheat", "No heat at home"),
        ("mobility", "Wheelchair or walker"), ("medical", "Medical device"), ("pets", "Pets"),
    ]
    static let outcomes: [(id: String, label: String)] = [
        ("moved", "Moved to a site"), ("water", "Brought water or supplies"), ("ok", "Checked, they're OK"),
        ("911", "Handed to 911"), ("not_found", "Couldn't find them"),
    ]
    static func need(_ id: String) -> String { needs.first { $0.id == id }?.label ?? id }
    static func flag(_ id: String) -> String { flags.first { $0.id == id }?.label ?? id }
    static func outcome(_ id: String) -> String { outcomes.first { $0.id == id }?.label ?? id }
}

// MARK: - Client

struct APIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

final class API {
    static let shared = API()
    let base: URL = {
        let s = Bundle.main.object(forInfoDictionaryKey: "SwelterAPIBase") as? String ?? "http://127.0.0.1:8000"
        return URL(string: s)!
    }()
    /// Set while someone is signed in: an Auth0 access token, or a demo account id when the server allows those.
    var bearer: String?
    var demoAccount: String?

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func request(_ method: String, _ path: String, query: [String: String?] = [:], body: [String: Any]? = nil) async throws -> Data {
        var c = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        let items = query.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }
        if !items.isEmpty { c.queryItems = items }
        var r = URLRequest(url: c.url!)
        r.httpMethod = method
        r.timeoutInterval = 30
        if let body {
            r.httpBody = try JSONSerialization.data(withJSONObject: body)
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let bearer { r.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization") }
        if let demoAccount { r.setValue(demoAccount, forHTTPHeaderField: "X-Demo-Account") }
        let (data, resp) = try await URLSession.shared.data(for: r)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw APIError(message: msg ?? "Server error \(code)")
        }
        return data
    }

    private func get<T: Decodable>(_ path: String, _ query: [String: String?] = [:]) async throws -> T {
        try decoder.decode(T.self, from: try await request("GET", path, query: query))
    }

    private func post<T: Decodable>(_ path: String, _ body: [String: Any] = [:]) async throws -> T {
        try decoder.decode(T.self, from: try await request("POST", path, body: body))
    }

    func config() async throws -> AppConfig { try await get("/api/config") }

    func live(replay: String?, hour: Int?) async throws -> Live {
        try await get("/api/live", ["replay": replay, "hour": replay == nil ? nil : hour.map(String.init)])
    }

    func sites(replay: String?, hour: Int?) async throws -> SitesResponse {
        try await get("/api/sites", ["replay": replay, "hour": replay == nil ? nil : hour.map(String.init)])
    }

    func presence(site: String, event: String, token: String) async throws {
        _ = try await request("POST", "/api/presence", body: ["site_id": site, "event": event, "token": token])
    }

    func ask(need: String, flags: [String], people: Int, at c: CLLocationCoordinate2D, callback: String, note: String) async throws -> Created {
        try await post("/api/requests", ["need": need, "flags": flags, "people": people, "lat": c.latitude,
                                         "lon": c.longitude, "callback": callback, "note": note])
    }

    func me() async throws -> Me { try await get("/api/me") }

    func saveProfile(name: String, home: Me.Home?, flags: [String], phone: String) async throws -> Me {
        var body: [String: Any] = ["name": name, "flags": flags, "phone": phone]
        if let h = home { body["home"] = ["name": h.name ?? "", "lat": h.lat, "lon": h.lon] }
        return try decoder.decode(Me.self, from: try await request("PUT", "/api/me", body: body))
    }

    func request(id: String, secret: String) async throws -> HelpRequest {
        try await get("/api/requests/\(id)", ["secret": secret])
    }

    func cancel(id: String, secret: String) async throws -> HelpRequest {
        try await post("/api/requests/\(id)/cancel", ["secret": secret])
    }

    func speak(_ text: String) async throws -> Data {
        try await request("POST", "/api/speak", body: ["text": text])
    }

    // responder
    func queue() async throws -> QueueResponse { try await get("/api/responder/requests") }

    func act(_ id: String, _ action: String, outcome: String? = nil) async throws -> HelpRequest {
        try await post("/api/responder/requests/\(id)/\(action)", outcome.map { ["outcome": $0] } ?? [:])
    }

    func report(site: String, level: String) async throws {
        _ = try await request("POST", "/api/responder/sites/\(site)/report", body: ["level": level])
    }

    func risk(replay: String?, hour: Int?) async throws -> RiskGrid {
        try await get("/api/responder/risk", ["replay": replay, "hour": hour.map(String.init)])
    }
}
