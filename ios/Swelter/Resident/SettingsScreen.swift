import SwiftUI

struct SettingsScreen: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Form {
                Section("Account") {
                    LabeledContent("Signed in as", value: model.name ?? "")
                    if let h = model.home { LabeledContent("Home", value: h.name ?? "Saved") }
                    if model.account?.demo == true { LabeledContent("Account", value: "Demo") }
                    Button("Sign out", role: .destructive) { model.signOut() }
                }

                Section {
                    Toggle(isOn: $model.crowdCounting) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Help count crowds at sites").font(.headline)
                            Text("Your phone says when it enters or leaves a city site, so everyone can see which ones have room.")
                                .font(.subheadline).foregroundStyle(Color.muted)
                        }
                    }
                    .tint(Color(hex: 0x1F8A63))
                    LabeledContent("We send", value: "Which site, in or out, time to 15 min")
                    LabeledContent("We never send", value: "Your location elsewhere, name, phone ID")
                    if model.crowdCounting && model.authStatus != .authorizedAlways {
                        Text("Crowd counting needs location access set to Always in Settings › Swelter › Location.")
                            .font(.footnote).foregroundStyle(Color.danger)
                    }
                } footer: {
                    Text("A site shows a phone-based level only after \(model.config?.kMin ?? 5) or more phones counted it. The code that marks your phone changes every day.")
                }

                Section("Language") {
                    Picker("Alerts", selection: $model.spanish) {
                        Text("English").tag(false)
                        Text("Español").tag(true)
                    }
                    .pickerStyle(.segmented)
                    if model.spanish && model.config?.translate != true {
                        Text("Spanish alerts need the server's Gemini key, which isn't set.").font(.footnote).foregroundStyle(Color.muted)
                    }
                }

                Section {
                    Picker("Day", selection: $model.replay) {
                        Text("Today (live)").tag(String?.none)
                        ForEach((model.config?.replayDays ?? [:]).sorted(by: { $0.key < $1.key }), id: \.key) { k, v in
                            Text("\(k.split(separator: "_").first.map { String($0).capitalized } ?? k): \(v)").tag(Optional(k))
                        }
                    }
                } header: {
                    Text("Replay a record day")
                } footer: {
                    Text("Replays a real recorded day's weather (NOAA, EPA) and Swelter's simulated crowds on today's clock, dated this year. Site hours are the city's current posted hours. The simulation covers 6 AM to 10 PM, so overnight there's no crowd forecast or risk layer.")
                }

                Section("Data") {
                    LabeledContent("Server", value: API.shared.base.host() ?? "")
                    LabeledContent("Storage", value: model.config?.db ?? "…")
                    LabeledContent("Voice (ElevenLabs)", value: model.config?.voice == true ? "On" : "Off")
                }
            }
            .navigationTitle("Settings")
            .onChange(of: model.replay) { Task { await model.refresh() } }
            .onChange(of: model.spanish) { Task { await model.refresh() } }
        }
    }
}
