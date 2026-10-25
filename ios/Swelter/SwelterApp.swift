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
                    if a.isGovernment {
                        GovernmentNotice()  // the planner is the web page
                    } else if a.profile == nil {
                        ProfileSetup()
                    } else if model.responderMode {
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
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.residentTab) {
            ResidentMap().tabItem { Label("Map", systemImage: "map") }.tag(0)
            HelpTab().tabItem { Label("Get help", systemImage: "hand.raised") }.tag(1)
            SettingsScreen().tabItem { Label("Settings", systemImage: "gearshape") }.tag(2)
        }
        // The hourly check-in comes up over whatever tab is open, and speaks. Checked here too (not only after a
        // refresh) so it shows right after sign-in, once these tabs are on screen.
        .sheet(item: $model.checkIn) { CheckInSheet(prompt: $0) }
        .task { model.maybeCheckIn() }
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
            TimelineView(.everyMinute) { t in
                HStack(spacing: 6) {
                    Image(systemName: "clock.arrow.circlepath")
                    Text("Simulation · \(model.live?.simulated?.label ?? model.config?.replayDays[r] ?? r) · \(t.date.formatted(date: .omitted, time: .shortened))")
                        .lineLimit(1).minimumScaleFactor(0.8)
                }
            }
            .font(.footnote.weight(.semibold))
            .padding(.horizontal, 12).padding(.vertical, 6)
            .frame(maxWidth: .infinity)
            .background(Color.ink, in: Capsule())
            .foregroundStyle(.white)
        }
    }
}
