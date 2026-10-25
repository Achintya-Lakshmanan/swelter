import SwiftUI

struct SitesBoard: View {
    @Environment(AppModel.self) private var model
    @State private var reporting: Site?
    @State private var error: String?

    var body: some View {
        let open = model.relevantSites.filter(\.openNow)
        NavigationStack {
            List {
                Section { ResponderHeader() }
                if let full = open.first(where: { $0.crowd.level == "full" && $0.crowd.source != "swelter forecast" }),
                   let alt = open.filter({ $0.crowd.level == "quiet" }).min(by: { $0.location.distance(from: full.location) < $1.location.distance(from: full.location) }) {
                    Section {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(full.name) is nearly full").font(.headline)
                            Text("Send people to \(alt.name) instead: quiet, \(String(format: "%.1f", alt.location.distance(from: full.location) / 1000)) km away, \(alt.hoursLine.lowerFirst).")
                                .font(.subheadline)
                        }
                        .listRowBackground(LevelStyle.of("full").bg)
                    }
                }
                Section {
                    if open.isEmpty { Text("No \(model.sitesMode) sites are open right now.").foregroundStyle(Color.muted) }
                    ForEach(open) { s in
                        Button { reporting = s } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(s.name).font(.headline).foregroundStyle(Color.ink)
                                    Text(s.hoursLine).font(.subheadline).foregroundStyle(Color.muted)
                                    SourceLine(text: s.crowd.sourceText)
                                }
                                Spacer()
                                LevelPill(level: s.crowd.level, forecast: s.crowd.source == "swelter forecast")
                            }
                        }
                    }
                } header: {
                    Text("\(open.count) open · \(model.sitesMode) sites")
                } footer: {
                    Text("Tap a site to report how busy it is. Your report shows for 2 hours and outranks phone counts and the forecast.")
                }
            }
            .navigationTitle("Sites")
            .refreshable { await model.refresh() }
            .confirmationDialog(reporting.map { "How busy is \($0.name)?" } ?? "", isPresented: Binding(get: { reporting != nil }, set: { if !$0 { reporting = nil } }), titleVisibility: .visible) {
                ForEach(["quiet", "busy", "full"], id: \.self) { lv in
                    Button(LevelStyle.of(lv).label) { report(lv) }
                }
            }
            .alert("Couldn't send the report", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {} message: { Text(error ?? "") }
        }
    }

    private func report(_ level: String) {
        guard let s = reporting else { return }
        Task {
            do {
                try await API.shared.report(site: s.id, level: level)
                await model.refresh()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
