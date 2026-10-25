import CoreLocation
import SwiftUI

struct HelpTab: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        NavigationStack {
            Group {
                if let r = model.activeRequest {
                    StatusScreen(id: r.id, secret: r.secret)
                } else {
                    HelpForm()
                }
            }
            .background(Color.bg)
        }
    }
}

struct Call911: View {
    var body: some View {
        Link(destination: URL(string: "tel:911")!) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Life-threatening? Call 911").font(.headline)
                Text("Confusion, fainting, no sweating, chest pain, trouble breathing").font(.subheadline)
            }
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(Color.danger, in: RoundedRectangle(cornerRadius: 14))
            .foregroundStyle(.white)
        }
    }
}

struct HelpForm: View {
    @Environment(AppModel.self) private var model
    @State private var need = "check"
    @State private var flags: Set<String> = []
    @State private var people = 1
    @State private var callback = ""
    @State private var note = ""
    @State private var place: String?
    @State private var sending = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Get help").font(.largeTitle.bold())
                Call911()

                Text("What do you need?").font(.headline)
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    ForEach(Labels.needs, id: \.id) { n in
                        let on = need == n.id
                        Button { need = n.id } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(n.label).font(.subheadline.weight(.semibold)).multilineTextAlignment(.leading)
                                Text(n.sub).font(.caption).opacity(0.85).multilineTextAlignment(.leading)
                            }
                            .frame(maxWidth: .infinity, minHeight: 74, alignment: .topLeading)
                            .padding(12)
                            .background(on ? Color.action : .white, in: RoundedRectangle(cornerRadius: 14))
                            .foregroundStyle(on ? .white : Color.ink)
                        }
                        .accessibilityAddTraits(on ? .isSelected : [])
                    }
                }

                Text("Anything a helper should know?").font(.headline)
                FlowChips(flags: $flags, options: Labels.flags.filter { model.sitesMode == "warming" ? $0.id != "noac" : $0.id != "noheat" })
                Stepper("People: \(people)", value: $people, in: 1...20)

                Card {
                    Label(place ?? (model.outsidePhilly ? "You're outside Philadelphia" : "Finding your location…"),
                          systemImage: model.atHome ? "house.fill" : "location.fill")
                        .font(.subheadline.weight(.semibold))
                    SourceLine(text: "Helpers see only this area (about 200 m) until one of them accepts.")
                }
                TextField("Callback number (optional)", text: $callback).keyboardType(.phonePad)
                    .padding(12).background(.white, in: RoundedRectangle(cornerRadius: 12))
                TextField("Note for the helper: floor, door, landmark (optional)", text: $note, axis: .vertical)
                    .lineLimit(2...4)
                    .padding(12).background(.white, in: RoundedRectangle(cornerRadius: 12))

                if let error { Text(error).foregroundStyle(Color.danger).font(.subheadline) }
                PrimaryButton(title: "Send to volunteers", busy: sending, action: send)
                    .disabled(model.helpLocation == nil)
                SourceLine(text: "Volunteers answer when they can. This is not 911.")
            }
            .padding(16)
        }
        .task(id: model.helpLocation?.coordinate.latitude) { await locate() }
        .onAppear {
            if flags.isEmpty, let f = model.account?.profile?.flags { flags = Set(f) }
            if callback.isEmpty, let p = model.account?.profile?.phone { callback = p }
        }
    }

    private func locate() async {
        guard let at = model.helpLocation else { return }
        let p = try? await CLGeocoder().reverseGeocodeLocation(at).first
        let street = p.map { [$0.subThoroughfare, $0.thoroughfare].compactMap { $0 }.joined(separator: " ") }
        if model.atHome {
            place = "Your home · " + (street ?? model.home?.name ?? "saved address")
        } else if let street {
            place = "Near " + street
        }
    }

    private func send() {
        guard let c = model.helpLocation?.coordinate else { return }
        sending = true
        Task {
            do {
                let r = try await API.shared.ask(need: need, flags: Array(flags), people: people, at: c, callback: callback, note: note)
                model.activeRequest = (r.id, r.secret)
            } catch {
                self.error = error.localizedDescription
            }
            sending = false
        }
    }
}

struct FlowChips: View {
    @Binding var flags: Set<String>
    let options: [(id: String, label: String)]
    var body: some View {
        ViewThatFits {
            wrap
        }
    }
    private var wrap: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 8)], alignment: .leading, spacing: 8) {
            ForEach(options, id: \.id) { o in
                let on = flags.contains(o.id)
                Button { if on { flags.remove(o.id) } else { flags.insert(o.id) } } label: {
                    Text(o.label).font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(on ? Color.ink : .white, in: Capsule())
                        .foregroundStyle(on ? .white : Color.ink)
                }
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }
}

struct StatusScreen: View {
    @Environment(AppModel.self) private var model
    let id: String
    let secret: String
    @State private var req: HelpRequest?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let r = req {
                    Text(headline(r)).font(.largeTitle.bold())
                    Text("\(Labels.need(r.need)) · sent \(timeLabel(ms: r.created))").foregroundStyle(Color.muted)
                    Card {
                        Step(done: true, title: "Sent to volunteers", time: timeLabel(ms: r.created))
                        Step(done: r.claimedName != nil, title: r.claimedName.map { "\($0) accepted" } ?? "Waiting for a volunteer",
                             time: r.claimedAt.map { timeLabel(ms: $0) })
                        Step(done: r.status == "done", title: r.outcome.map { "Done: \(Labels.outcome($0).lowercased())" } ?? "Done",
                             time: r.closedAt.map { timeLabel(ms: $0) })
                    }
                    if r.status == "open" || r.status == "claimed" {
                        Card {
                            Text("While you wait").font(.headline)
                            ForEach(tips, id: \.self) { Text("• \($0)") }
                            SourceLine(text: model.sitesMode == "warming" ? "CDC winter weather guidance" : "CDC heat illness guidance")
                        }
                        Call911()
                        Button("Cancel request", role: .destructive) {
                            Task { req = try? await API.shared.cancel(id: id, secret: secret) }
                        }
                        .frame(maxWidth: .infinity)
                    } else {
                        PrimaryButton(title: "Done") { model.activeRequest = nil }
                    }
                } else if let error {
                    Text(error).foregroundStyle(Color.danger)
                    Button("Start over") { model.activeRequest = nil }
                } else {
                    ProgressView()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
        }
        .task {
            while !Task.isCancelled {
                do {
                    req = try await API.shared.request(id: id, secret: secret)
                    error = nil
                } catch {
                    if error.localizedDescription == "not found" { model.activeRequest = nil; return }  // server data was reset
                    self.error = error.localizedDescription
                }
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    private func headline(_ r: HelpRequest) -> String {
        switch r.status {
        case "claimed": "Help is on the way"
        case "done": "Closed"
        case "cancelled": "Request cancelled"
        default: "Request sent"
        }
    }

    private var tips: [String] {
        model.sitesMode == "warming"
            ? ["Stay in one warm room and close off the others.", "Wear layers, a hat and dry socks.", "Never heat with an oven or a grill."]
            : ["Move to the coolest room, away from windows.", "Sip water, even if you're not thirsty.", "Put a cool, wet cloth on your neck and wrists."]
    }
}

private struct Step: View {
    let done: Bool, title: String, time: String?
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle").foregroundStyle(done ? Color(hex: 0x1F8A63) : Color.muted)
            Text(title).font(.body.weight(done ? .semibold : .regular))
            Spacer()
            if let time { Text(time).font(.footnote).foregroundStyle(Color.muted) }
        }
    }
}
