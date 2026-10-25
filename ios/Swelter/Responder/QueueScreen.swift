import CoreLocation
import MapKit
import SwiftUI

struct QueueScreen: View {
    @Environment(AppModel.self) private var model
    @State private var data = ResponderData.shared
    @State private var filter = "all"

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ResponderHeader()
                    Picker("Need", selection: $filter) {
                        Text("All").tag("all")
                        ForEach(Labels.needs, id: \.id) { Text($0.id.capitalized).tag($0.id) }
                    }
                    .pickerStyle(.segmented)
                }
                Section {
                    let rows = data.sorted.filter { filter == "all" || $0.need == filter }
                    if rows.isEmpty {
                        Text(data.error ?? "No open requests.").foregroundStyle(Color.muted)
                    }
                    ForEach(rows) { r in
                        NavigationLink(value: r.id) {
                            VStack(alignment: .leading, spacing: 4) {
                                HStack {
                                    Text(headline(r)).font(.headline)
                                    Spacer()
                                    Text(r.mine == true ? "Yours" : "\(r.minutesWaiting ?? 0) min")
                                        .font(.footnote.weight(.bold))
                                        .foregroundStyle(r.mine == true ? Color.action : (r.minutesWaiting ?? 0) >= 20 ? Color.danger : Color.muted)
                                }
                                Text(whoLine(r)).font(.subheadline).foregroundStyle(Color.muted)
                                if let c = r.coordinate {
                                    Text(String(format: "%.1f km %@", model.origin.distance(from: CLLocation(latitude: c.latitude, longitude: c.longitude)) / 1000,
                                                r.exact == true ? "away" : "away (approximate)"))
                                        .font(.footnote).foregroundStyle(Color.muted)
                                }
                            }
                        }
                    }
                } header: {
                    Text("Most urgent first")
                } footer: {
                    Text("Order: minutes waiting, plus 15 for each risk factor (65+, alone, no AC or heat, medical device, mobility).")
                }
            }
            .navigationTitle("Requests")
            .navigationDestination(for: String.self) { id in
                if let r = data.requests.first(where: { $0.id == id }) { RequestDetail(request: r) }
            }
            .refreshable { await data.refresh(model) }
        }
    }
}

struct RequestDetail: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State var request: HelpRequest
    @State private var address: String?
    @State private var busy = false
    @State private var error: String?
    @State private var closing = false

    var body: some View {
        let r = request
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ReplayBanner()
                HStack {
                    Text("Waiting \(r.minutesWaiting ?? 0) min").font(.footnote.weight(.bold))
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(Color.danger.opacity(0.12), in: Capsule()).foregroundStyle(Color.danger)
                    if let c = r.coordinate {
                        Text(String(format: "%.1f km", model.origin.distance(from: CLLocation(latitude: c.latitude, longitude: c.longitude)) / 1000))
                            .font(.footnote).foregroundStyle(Color.muted)
                    }
                }
                if let n = r.name, r.status == "open" || r.mine == true {
                    Text("\(n) asked for help").font(.largeTitle.bold())
                    Text(Labels.need(r.need)).font(.title3.weight(.semibold))
                } else {
                    Text(Labels.need(r.need)).font(.largeTitle.bold())
                }
                Text(whoLine(r)).foregroundStyle(Color.muted)

                if r.status == "done" {
                    Card {
                        Text("Closed: \(Labels.outcome(r.outcome ?? ""))").font(.headline)
                        Text("The resident sees this on their status screen. Thank you.")
                    }
                    PrimaryButton(title: "Back to the queue") { dismiss() }
                } else if r.mine == true {
                    Card {
                        Label(address ?? "Finding the address…", systemImage: "mappin.and.ellipse").font(.headline)
                        if let n = r.note { Text(n) }
                        if let cb = r.callback, !cb.isEmpty { Text("Callback: \(cb)") }
                        if let s = nearestWithRoom { Text("Nearest with room: **\(s.name)** · \(s.crowd.levelText.lowercased()) · \(s.hoursLine.lowerFirst)") }
                    }
                    PrimaryButton(title: "Navigate") { navigate() }
                    if let cb = r.callback, let url = URL(string: "tel:\(cb.filter(\.isNumber))") {
                        Link("Call them", destination: url).font(.headline).frame(maxWidth: .infinity, minHeight: 50)
                            .background(.white, in: RoundedRectangle(cornerRadius: 14))
                    }
                    PrimaryButton(title: "Close it out", color: .ink) { closing = true }
                    Button("Release it back to the queue") { act("release") }.frame(maxWidth: .infinity)
                } else if r.status == "claimed" {
                    Card { Text("\(r.claimedName ?? "Another responder") accepted this.") }
                } else {
                    Card {
                        Text("The exact location, note and callback number appear when you accept. Until then it shows within about 200 m.")
                            .foregroundStyle(Color.muted)
                    }
                    PrimaryButton(title: "Accept · I'll go", busy: busy) { act("claim") }
                    Button("Not for me") { dismiss() }.frame(maxWidth: .infinity)
                }
                if let error { Text(error).foregroundStyle(Color.danger).font(.subheadline) }
            }
            .padding(16)
        }
        .background(Color.bg)
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("How did it end?", isPresented: $closing, titleVisibility: .visible) {
            ForEach(Labels.outcomes, id: \.id) { o in
                Button(o.label, role: o.id == "911" ? .destructive : nil) { act("done", outcome: o.id) }
            }
        }
        .task(id: r.exact) { await geocode() }
    }

    private var nearestWithRoom: Site? {
        guard let c = request.coordinate else { return nil }
        let here = CLLocation(latitude: c.latitude, longitude: c.longitude)
        return model.relevantSites.filter { $0.openNow && $0.crowd.level != "full" }
            .min { here.distance(from: $0.location) < here.distance(from: $1.location) }
    }

    private func act(_ action: String, outcome: String? = nil) {
        busy = true
        Task {
            do {
                request = try await API.shared.act(request.id, action, outcome: outcome)
                ResponderData.shared.replace(request)
                error = nil
                if action == "release" { dismiss() }
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }

    private func geocode() async {
        guard request.exact == true, let c = request.coordinate else { return }
        let p = try? await CLGeocoder().reverseGeocodeLocation(CLLocation(latitude: c.latitude, longitude: c.longitude)).first
        address = p.map { [$0.subThoroughfare, $0.thoroughfare].compactMap { $0 }.joined(separator: " ") }
            ?? String(format: "%.5f, %.5f", c.latitude, c.longitude)
    }

    private func navigate() {
        guard let c = request.coordinate else { return }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: c))
        item.name = request.name.map { "\($0) · \(Labels.need(request.need))" } ?? Labels.need(request.need)
        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDefault])
    }
}
