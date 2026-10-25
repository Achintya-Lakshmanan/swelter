import CoreLocation
import SwiftUI

/// One sign-in for everyone. Auth0 decides who is a responder (an organiser grants the role); the rest are residents.
struct SignInScreen: View {
    @Environment(AppModel.self) private var model
    @State private var login = Auth0Login()
    @State private var busy: String?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Swelter").font(.system(size: 44, weight: .bold)).foregroundStyle(Color.ink)
                    Text("Cooling and warming sites in Philadelphia, how busy they are, and neighbours who can come help.")
                        .foregroundStyle(Color.muted)
                }
                .padding(.top, 40)

                if let a = model.config?.auth0, a.enabled, let domain = a.domain, let client = a.clientId {
                    PrimaryButton(title: "Sign in", busy: busy == "auth0") { auth0(domain, client, a.audience) }
                    SourceLine(text: "Secured by Auth0 · \(domain). Residents and responders use the same sign-in; your organisation makes you a responder.")
                } else if model.config != nil, model.config?.auth0.demoAccounts.isEmpty == true {
                    Text("Sign-in isn't set up on this server yet (AUTH0_DOMAIN is empty).").foregroundStyle(Color.danger)
                }

                if let demos = model.config?.auth0.demoAccounts, !demos.isEmpty {
                    Text("Demo accounts").font(.headline).padding(.top, 8)
                    ForEach(demos) { d in
                        Button { demo(d.id) } label: {
                            HStack(spacing: 12) {
                                Image(systemName: d.role == "responder" ? "cross.case.fill" : "house.fill")
                                    .font(.title3).frame(width: 40, height: 40)
                                    .background((d.role == "responder" ? Color.action : Color.danger).opacity(0.12), in: Circle())
                                    .foregroundStyle(d.role == "responder" ? Color.action : Color.danger)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(d.name).font(.headline).foregroundStyle(Color.ink)
                                    Text(d.about).font(.subheadline).foregroundStyle(Color.muted)
                                }
                                .multilineTextAlignment(.leading)
                                Spacer()
                                if busy == d.id { ProgressView() } else { Image(systemName: "chevron.right").foregroundStyle(Color.muted) }
                            }
                            .padding(14)
                            .background(.white, in: RoundedRectangle(cornerRadius: 16))
                        }
                    }
                    SourceLine(text: "Kayla is resident #1484 in Swelter's simulation. Demo accounts are on only while the server runs with SWELTER_DEV_LOGIN=1.")
                }

                if model.config == nil {
                    if let e = model.loadError {
                        Text("Can't reach the Swelter server: \(e)").foregroundStyle(Color.danger)
                        Button("Try again") { Task { await model.refresh() } }
                    } else {
                        ProgressView()
                    }
                }
                if let error { Text(error).foregroundStyle(Color.danger).font(.subheadline) }
            }
            .padding(20)
        }
        .background(Color.bg)
    }

    private func demo(_ id: String) {
        busy = id
        Task {
            await model.signIn(demo: id)
            error = model.account == nil ? model.loadError : nil
            busy = nil
        }
    }

    private func auth0(_ domain: String, _ client: String, _ audience: String?) {
        busy = "auth0"
        Task {
            do {
                let s = try await login.signIn(domain: domain, clientId: client, audience: audience)
                ProfileSetup.suggestedName = s.name
                await model.signIn(token: s.accessToken)
                error = model.account == nil ? model.loadError : nil
            } catch {
                self.error = error.localizedDescription
            }
            busy = nil
        }
    }
}

/// First sign-in: a name, and for residents a home address (used when the phone isn't in Philadelphia) and
/// anything a helper should know, which pre-fills help requests.
struct ProfileSetup: View {
    static var suggestedName: String?
    @Environment(AppModel.self) private var model
    @State private var name = ProfileSetup.suggestedName ?? ""
    @State private var address = ""
    @State private var home: Me.Home?
    @State private var flags: Set<String> = []
    @State private var phone = ""
    @State private var busy = false
    @State private var error: String?

    private var responder: Bool { model.account?.isResponder == true }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Your name", text: $name).textContentType(.name)
                } footer: {
                    Text(responder ? "Residents see your name when you accept their request." : "Volunteers see your first name when you ask for help.")
                }
                if !responder {
                    Section {
                        TextField("Home address", text: $address).textContentType(.fullStreetAddress)
                            .onSubmit { Task { await findAddress() } }
                        if let h = home { Label(h.name ?? "", systemImage: "checkmark.circle.fill").foregroundStyle(Color(hex: 0x1F8A63)) }
                        Button("Check address") { Task { await findAddress() } }.disabled(address.isEmpty)
                    } header: { Text("Home") } footer: {
                        Text("Optional. Used for distances and help requests when your phone can't tell where you are.")
                    }
                    Section("Anything a helper should know?") {
                        ForEach(Labels.flags, id: \.id) { f in
                            Toggle(f.label, isOn: Binding(get: { flags.contains(f.id) }, set: { on in if on { flags.insert(f.id) } else { flags.remove(f.id) } }))
                        }
                    }
                }
                Section {
                    TextField("Phone (optional)", text: $phone).keyboardType(.phonePad)
                }
                if let error { Text(error).foregroundStyle(Color.danger) }
                Section {
                    Button(busy ? "Saving…" : "Continue") { save() }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                    Button("Sign out", role: .destructive) { model.signOut() }
                }
            }
            .navigationTitle(responder ? "Responder profile" : "About you")
        }
    }

    private func findAddress() async {
        let philly = CLCircularRegion(center: cityHall, radius: 20000, identifier: "philly")
        guard let p = try? await CLGeocoder().geocodeAddressString(address, in: philly).first, let c = p.location?.coordinate else {
            error = "Couldn't find that address."
            return
        }
        guard inPhilly(c) else { error = "Swelter only covers Philadelphia."; return }
        error = nil
        home = .init(name: [p.subThoroughfare, p.thoroughfare].compactMap { $0 }.joined(separator: " "), lat: c.latitude, lon: c.longitude)
    }

    private func save() {
        busy = true
        Task {
            do {
                model.account = try await API.shared.saveProfile(name: name, home: home, flags: Array(flags), phone: phone)
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}
