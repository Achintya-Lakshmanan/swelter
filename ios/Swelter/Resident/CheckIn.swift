import SwiftUI

/// Hourly "are you okay?" check-in while the weather is dangerous, spoken aloud (ElevenLabs). If the resident doesn't
/// answer in time, the app asks a volunteer to check on them, as a regular "Check on someone" request.
struct CheckInPrompt: Identifiable {
    let id = UUID()
    let hour: Int
    let hazard: String
    let reading: String       // "119°F heat index"
    let words: String         // "extreme danger"
    let homeLine: String?     // "Your home has no AC."
    let spoken: String
    let deadline: Date
}

extension AppModel {
    private var flags: Set<String> { Set(account?.profile?.flags ?? []) }
    private var firstName: String { name?.split(separator: " ").first.map(String.init) ?? "there" }

    /// After each refresh: one check-in per clock hour (per replay day) while the reading is at danger or worse.
    @MainActor
    func maybeCheckIn() {
        guard checkInsOn, account != nil, !responderMode, activeRequest == nil, checkIn == nil,
              let d = live?.danger else { return }
        let vulnerable = !flags.isDisjoint(with: ["older", "medical"])
        guard (vulnerable ? d.vulnerableLevel : d.level) >= 2 else { return }
        let key = "\(replay ?? "live")|\(Date().formatted(.iso8601.year().month().day()))|\(clockHour)"
        guard UserDefaults.standard.string(forKey: "lastCheckIn") != key else { return }
        UserDefaults.standard.set(key, forKey: "lastCheckIn")
        startCheckIn()
    }

    /// Also used by Settings › Try a check-in now, whatever the danger level.
    @MainActor
    func startCheckIn() {
        guard let d = live?.danger else { return }
        let vulnerable = !flags.isDisjoint(with: ["older", "medical"])
        let words = vulnerable ? d.vulnerableWords : d.words
        let v = Int(d.value.rounded())
        let (reading, said): (String, String) = switch d.hazard {
        case "heat": ("\(v)°F heat index", "the heat index is \(v) degrees")
        case "cold": ("\(v)°F wind chill", "the wind chill is \(v < 0 ? "minus \(-v)" : "\(v)") degrees")
        case "smoke": ("AQI \(v)", "the air quality index is \(v)")
        default: (String(format: "%.1f in of rain in 3 h", d.value), String(format: "%.1f inches of rain fell in the last 3 hours", d.value))
        }
        let home = d.hazard == "heat" && flags.contains("noac") ? "Your home has no AC."
            : d.hazard == "cold" && flags.contains("noheat") ? "Your home has no heat." : nil
        let time = hourLabel(clockHour)
        let spoken = "Hi \(firstName). It's \(time), and \(said). That's \(words)."
            + (home.map { " \($0)" } ?? "")
            + " Are you okay? Tap I'm OK, or I need help. If you don't answer in \(checkInWait) minutes,"
            + " I'll ask a volunteer nearby to check on you."
        checkIn = CheckInPrompt(hour: clockHour, hazard: d.hazard, reading: reading, words: words, homeLine: home,
                                spoken: spoken, deadline: Date().addingTimeInterval(Double(checkInWait) * 60))
    }
}

struct CheckInSheet: View {
    @Environment(AppModel.self) private var model
    let prompt: CheckInPrompt
    @State private var sending = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Are you okay?").font(.largeTitle.bold())
                Card {
                    Text("\(prompt.reading) at \(hourLabel(prompt.hour))").font(.title3.bold())
                    Text(prompt.words.prefix(1).uppercased() + prompt.words.dropFirst()).font(.headline).foregroundStyle(Color.danger)
                    if let h = prompt.homeLine { Text(h) }
                }
                TimelineView(.periodic(from: .now, by: 1)) { ctx in
                    let left = max(0, Int(prompt.deadline.timeIntervalSince(ctx.date)))
                    Text("If you don't answer in **\(left / 60):\(String(format: "%02d", left % 60))**, we'll ask a volunteer nearby to check on you.")
                        .font(.body)
                }
                PrimaryButton(title: "I'm OK", color: Color(hex: 0x1F8A63), busy: false) { okay() }
                PrimaryButton(title: "I need help", color: .danger, busy: sending) { Task { await send(answered: true) } }
                Button { Task { await model.speak(prompt.spoken) } } label: {
                    Label("Hear it again", systemImage: "speaker.wave.2.fill").frame(maxWidth: .infinity)
                }
                if let error { Text(error).foregroundStyle(Color.danger).font(.subheadline) }
                Call911()
                SourceLine(text: "ChillySOS checks in every hour while the weather is at danger level or worse. Turn it off in Settings.")
            }
            .padding(16)
        }
        .background(Color.bg)
        .interactiveDismissDisabled()
        .task {
            await model.speak(prompt.spoken)
            // Keeps waiting while the app is open; if the app was closed past the deadline, it sends on return.
            while !Task.isCancelled && !sending {
                if Date() >= prompt.deadline { await send(answered: false); return }
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private func okay() {
        let tip = switch prompt.hazard {
        case "heat": "Stay in the coolest room and keep sipping water."
        case "cold": "Stay in one warm room and keep your layers on."
        case "smoke": "Keep the windows closed and stay inside."
        default: "Stay off flooded streets and away from basements."
        }
        model.checkIn = nil
        Task { await model.speak("Thanks. \(tip) I'll check on you again at \(hourLabel((prompt.hour + 1) % 24)).") }
    }

    @MainActor
    private func send(answered: Bool) async {
        guard !sending else { return }
        guard let at = model.helpLocation?.coordinate else {
            error = "Can't find your location or a saved home address, so no one can be sent. Call 911 if you feel unwell."
            return
        }
        sending = true
        let when = hourLabel(prompt.hour)
        let note = answered ? "Asked for help at the \(when) check-in (\(prompt.reading))."
            : "No answer to the \(when) check-in (\(prompt.reading)). Sent automatically."
        do {
            let p = model.account?.profile
            let r = try await API.shared.ask(need: "check", flags: p?.flags ?? [], people: 1, at: at,
                                             callback: p?.phone ?? "", note: note)
            model.activeRequest = (r.id, r.secret)
            model.residentTab = 1
            model.checkIn = nil
            await model.speak(answered ? "I've asked volunteers nearby to come check on you. I'll tell you when someone accepts."
                              : "You didn't answer, so I've asked a volunteer nearby to check on you. I'll tell you when someone accepts.")
        } catch {
            self.error = error.localizedDescription
            sending = false
        }
    }
}
