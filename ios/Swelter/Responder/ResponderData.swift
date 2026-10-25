import CoreLocation
import Observation
import SwiftUI
import UIKit

/// The responder's live queue and risk layer, polled while on duty.
@Observable
final class ResponderData {
    static let shared = ResponderData()
    var requests: [HelpRequest] = []
    var risk: RiskGrid?
    var error: String?
    var onDuty = true
    /// A request this responder hasn't seen yet, shown as a pop-up.
    var incoming: HelpRequest?
    private var seen: Set<String> = []
    /// Replay day and hour of the risk grid on screen; the grid only changes when this does.
    private var riskKey: String?

    var sorted: [HelpRequest] { requests.sorted { ($0.mine == true ? 0 : 1, -$0.urgency) < ($1.mine == true ? 0 : 1, -$1.urgency) } }

    @MainActor
    func refresh(_ model: AppModel) async {
        do {
            requests = try await API.shared.queue().requests
            if incoming == nil, let r = sorted.first(where: { $0.status == "open" && $0.mine != true && !seen.contains($0.id) }) {
                seen.insert(r.id)
                incoming = r
                UINotificationFeedbackGenerator().notificationOccurred(.warning)
                if model.speakUpdates { Task { await model.speak(spoken(r, from: model.origin)) } }
            }
            // Re-fetching (and re-drawing ~400 map cells) every 5 s kept Apple Maps busy enough that iOS killed the
            // app with a watchdog timeout; fetch it again only when the hour or the replay day changes.
            let key = "\(model.replay ?? "live")|\(model.clockHour)"
            if key != riskKey || risk == nil {
                risk = try await API.shared.risk(replay: model.replay, hour: model.replay != nil ? model.replayHour : nil)
                riskKey = key
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    @MainActor
    func poll(_ model: AppModel) async {
        while !Task.isCancelled {
            if onDuty { await refresh(model) }
            try? await Task.sleep(for: .seconds(5))
        }
    }

    /// What the pop-up reads aloud: "New help request. Kayla, Check on someone. 1 person, 65 or older. 1.2 kilometers away."
    private func spoken(_ r: HelpRequest, from origin: CLLocation) -> String {
        var parts = ["New help request", headline(r), whoLine(r)].map { $0.replacingOccurrences(of: " · ", with: ", ") }
        if let c = r.coordinate {
            let km = origin.distance(from: CLLocation(latitude: c.latitude, longitude: c.longitude)) / 1000
            parts.append(String(format: "%.1f kilometers away", km))
        }
        return parts.joined(separator: ". ") + "."
    }

    func reset() {
        requests = []
        risk = nil
        riskKey = nil
        incoming = nil
        seen = []
    }

    func replace(_ r: HelpRequest) {
        if let i = requests.firstIndex(where: { $0.id == r.id }) { requests[i] = r }
        if r.status == "done" || r.status == "cancelled" { requests.removeAll { $0.id == r.id } }
    }
}

/// Header shared by the responder tabs: who's signed in, duty toggle, sign out.
struct ResponderHeader: View {
    @Environment(AppModel.self) private var model
    @State private var data = ResponderData.shared

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Responder · \(model.name ?? "")").font(.footnote.weight(.semibold)).foregroundStyle(Color.muted)
                Text(data.onDuty ? "On duty" : "Off duty").font(.headline)
            }
            Spacer()
            Toggle("On duty", isOn: $data.onDuty).labelsHidden().tint(Color(hex: 0x1F8A63))
            Menu {
                Button("I need help: switch to resident view", systemImage: "hand.raised") {
                    model.residentTab = 1
                    model.actingAsResident = true
                }
                Button("Sign out", role: .destructive) { model.signOut() }
            } label: { Image(systemName: "person.crop.circle").font(.title2) }
        }
    }
}
