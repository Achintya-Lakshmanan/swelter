import SwiftUI

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
    static let bg = Color(hex: 0xF4F6F7)
    static let ink = Color(hex: 0x14212B)
    static let muted = Color(hex: 0x51616C)
    static let action = Color(hex: 0x1D5FD1)
    static let danger = Color(hex: 0xB3261E)
    static let line = Color(hex: 0xDDE3E7)
}

/// Crowd level colors from the design: pill background, pill text, map pin.
struct LevelStyle {
    let label: String, bg: Color, text: Color, pin: Color

    static func of(_ level: String?) -> LevelStyle {
        switch level {
        case "quiet": LevelStyle(label: "Quiet", bg: Color(hex: 0xE3F3EC), text: Color(hex: 0x17694E), pin: Color(hex: 0x1F8A63))
        case "busy": LevelStyle(label: "Busy", bg: Color(hex: 0xFFF1D6), text: Color(hex: 0x8A5300), pin: Color(hex: 0xD08A00))
        case "full": LevelStyle(label: "Nearly full", bg: Color(hex: 0xFDE4D8), text: Color(hex: 0xA3340B), pin: Color(hex: 0xC2410C))
        default: LevelStyle(label: "No crowd data", bg: Color(hex: 0xE8ECEF), text: .muted, pin: Color(hex: 0x6B7A85))
        }
    }
}

struct LevelPill: View {
    let level: String?
    /// Forecast levels are relative to the site's own busiest simulated hour, not its capacity.
    var forecast = false
    var body: some View {
        let s = LevelStyle.of(level)
        let forecastLabel = ["quiet": "Quiet hour", "busy": "Busy hour", "full": "Peak hour"][level ?? ""]
        Text(forecast ? (forecastLabel ?? s.label) : s.label)
            .font(.footnote.weight(.semibold))
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(s.bg, in: Capsule())
            .foregroundStyle(s.text)
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 10) { content }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct PrimaryButton: View {
    let title: String
    var color: Color = .action
    var busy = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack {
                if busy { ProgressView().tint(.white) }
                Text(title).font(.headline)
            }
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(color, in: RoundedRectangle(cornerRadius: 14))
            .foregroundStyle(.white)
        }
        .disabled(busy)
    }
}

/// Small grey line saying where a number comes from.
struct SourceLine: View {
    let text: String
    var body: some View {
        Text(text).font(.caption).foregroundStyle(Color.muted)
    }
}

func hourLabel(_ h: Int) -> String {
    let h12 = (h + 11) % 12 + 1
    return "\(h12) \(h < 12 || h == 24 ? "AM" : "PM")"
}

func timeLabel(ms: Int) -> String {
    Date(timeIntervalSince1970: Double(ms) / 1000).formatted(date: .omitted, time: .shortened)
}

extension String {
    /// "Open until 9 AM" → "open until 9 AM" for use mid-sentence.
    var lowerFirst: String { prefix(1).lowercased() + dropFirst() }
}
