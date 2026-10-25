import SwiftUI

@main
struct SwelterApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            Group {
                if model.restoring {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity).background(Color.bg)
                } else if let a = model.account {
                    if a.profile == nil {
                        ProfileSetup()
                    } else if a.isResponder {
                        ResponderTabs()
                    } else {
                        ResidentTabs()
                    }
                } else {
                    SignInScreen()
                }
            }
            .environment(model)
            .tint(.action)
            .onAppear { model.start() }
        }
    }
}

struct ResidentTabs: View {
    var body: some View {
        TabView {
            ResidentMap().tabItem { Label("Map", systemImage: "map") }
            HelpTab().tabItem { Label("Get help", systemImage: "hand.raised") }
            SettingsScreen().tabItem { Label("Settings", systemImage: "gearshape") }
        }
    }
}

struct ResponderTabs: View {
    @Environment(AppModel.self) private var model
    @State private var data = ResponderData.shared

    var body: some View {
        TabView {
            DutyMap().tabItem { Label("Map", systemImage: "map") }
            QueueScreen().tabItem { Label("Queue", systemImage: "list.bullet") }
            SitesBoard().tabItem { Label("Sites", systemImage: "building.2") }
        }
        .task { await data.poll(model) }
        // A new request pops up over whatever tab is open: "Kayla asked for help", accept, navigate.
        .sheet(item: $data.incoming) { r in
            NavigationStack {
                RequestDetail(request: r)
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { data.incoming = nil } } }
            }
            .presentationDetents([.large])
        }
    }
}

/// Shown on every screen while a stored record day is replayed, so it is never mistaken for today.
struct ReplayBanner: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if let r = model.replay {
            HStack(spacing: 6) {
                Image(systemName: "clock.arrow.circlepath")
                Text("Replay: \(model.config?.replayDays[r] ?? r) at \(hourLabel(model.replayHour)). Not today.")
                    .lineLimit(1).minimumScaleFactor(0.8)
            }
            .font(.footnote.weight(.semibold))
            .padding(.horizontal, 12).padding(.vertical, 6)
            .frame(maxWidth: .infinity)
            .background(Color.ink, in: Capsule())
            .foregroundStyle(.white)
        }
    }
}
