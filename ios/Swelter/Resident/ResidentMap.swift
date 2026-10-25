import MapKit
import SwiftUI

/// Walking times from Apple Maps, cached per site for the session.
@Observable
final class WalkTimes {
    static let shared = WalkTimes()
    var minutes: [String: Int] = [:]
    private var asked: Set<String> = []
    private var from: CLLocation?

    func request(_ site: Site, from origin: CLLocation) {
        if let f = from, f.distance(from: origin) > 150 { minutes = [:]; asked = [] }  // moved, or location just arrived
        from = origin
        guard !asked.contains(site.id) else { return }
        asked.insert(site.id)
        let r = MKDirections.Request()
        r.source = MKMapItem(placemark: MKPlacemark(coordinate: origin.coordinate))
        r.destination = MKMapItem(placemark: MKPlacemark(coordinate: site.coordinate))
        r.transportType = .walking
        MKDirections(request: r).calculateETA { [weak self] eta, _ in
            guard let t = eta?.expectedTravelTime else { return }
            DispatchQueue.main.async { self?.minutes[site.id] = Int((t / 60).rounded()) }
        }
    }

    func label(_ site: Site, model: AppModel) -> String {
        if let m = minutes[site.id] { return "\(m) min walk" }
        let km = model.distance(to: site) / 1000
        return String(format: "%.1f km away", km)
    }
}

struct ResidentMap: View {
    @Environment(AppModel.self) private var model
    @State private var camera: MapCameraPosition = .region(MKCoordinateRegion(center: cityHall, latitudinalMeters: 5000, longitudinalMeters: 5000))
    @State private var selected: Site?
    @State private var showAlert = false

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Map(position: $camera, selection: $selected) {
                    UserAnnotation()
                    if model.atHome, let h = model.homeLocation {
                        Annotation("Home", coordinate: h.coordinate) {
                            Image(systemName: "house.fill").font(.footnote.weight(.bold)).foregroundStyle(.white)
                                .frame(width: 30, height: 30).background(Color.ink, in: Circle())
                                .overlay(Circle().stroke(.white, lineWidth: 2))
                        }
                    }
                    ForEach(model.relevantSites) { s in
                        Annotation(s.name, coordinate: s.coordinate, anchor: .bottom) {
                            SitePin(site: s)
                        }
                        .tag(s)
                        .annotationTitles(.hidden)
                    }
                }
                .mapControls { MapUserLocationButton() }

                VStack(spacing: 8) {
                    ReplayBanner()
                    HazardCard(showDetail: $showAlert)
                }
                .padding(.horizontal, 12).padding(.top, 4)
            }
            .safeAreaInset(edge: .bottom) { NearbyPanel(selected: $selected) }
            .navigationDestination(item: $selected) { SiteDetail(site: $0) }
            .sheet(isPresented: $showAlert) { AlertDetail() }
            .toolbar(.hidden, for: .navigationBar)
            .refreshable { await model.refresh() }
            .onChange(of: model.here == nil) { recenter() }
            .onChange(of: model.atHome) { recenter() }
            .onAppear(perform: recenter)
        }
    }

    private func recenter() {
        camera = .region(MKCoordinateRegion(center: model.origin.coordinate, latitudinalMeters: 3200, longitudinalMeters: 3200))
    }
}

struct SitePin: View {
    let site: Site
    var body: some View {
        let s = LevelStyle.of(site.openNow ? site.crowd.level : nil)
        Image(systemName: site.openNow ? "building.columns.fill" : "building.columns")
            .font(.system(size: site.openNow ? 14 : 10, weight: .semibold))
            .foregroundStyle(.white)
            .padding(site.openNow ? 7 : 5)
            .background(site.openNow ? s.pin : Color(hex: 0x9AA6AE), in: Circle())
            .overlay(Circle().stroke(.white, lineWidth: 2))
            .accessibilityLabel("\(site.name), \(site.openNow ? s.label : "closed")")
    }
}

/// Top card: the active NWS alert if there is one, otherwise the observed conditions.
struct HazardCard: View {
    @Environment(AppModel.self) private var model
    @Binding var showDetail: Bool

    var body: some View {
        if let live = model.live {
            let alert = live.alerts.first { $0.hazard != nil } ?? live.alerts.first
            Button { showDetail = true } label: {
                VStack(alignment: .leading, spacing: 4) {
                    if let a = alert {
                        Text(a.event).font(.headline)
                        Text(conditionsLine(live)).font(.subheadline)
                    } else {
                        Text(live.replay ? (live.conditions.label ?? "Weather alert") : "No weather alerts for Philadelphia").font(.headline)
                        Text(conditionsLine(live)).font(.subheadline)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(alert?.hazard != nil || live.replay ? Color.danger : Color.ink, in: RoundedRectangle(cornerRadius: 16))
                .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
        } else if let e = model.loadError {
            Text("Can't reach Swelter: \(e)").font(.footnote).padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.white, in: RoundedRectangle(cornerRadius: 14))
        }
    }
}

func conditionsLine(_ live: Live) -> String {
    let c = live.conditions
    if live.replay, let v = c.value, let u = c.unit {
        let now = Calendar.current.component(.hour, from: Date())
        return "\(Int(v.rounded())) \(u) " + (c.hour == now ? "now" : "at \(hourLabel(c.hour ?? 12))")
    }
    var parts: [String] = []
    if let t = c.tempF { parts.append("\(t)°F at PHL") }
    if let hi = c.heatIndexF, hi > (c.tempF ?? 0) { parts.append("feels like \(hi)°F") }
    if let wc = c.windChillF, wc < (c.tempF ?? 999) { parts.append("wind chill \(wc)°F") }
    if let a = c.aqi { parts.append("AQI \(a)") }
    return parts.joined(separator: " · ")
}

struct NearbyPanel: View {
    @Environment(AppModel.self) private var model
    @Binding var selected: Site?
    @State private var walk = WalkTimes.shared

    var body: some View {
        let open = model.relevantSites.filter(\.openNow).prefix(3)
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(open.isEmpty ? "Nothing open right now" : "Open near you").font(.title3.bold())
                Spacer()
                Text("\(model.sitesMode.capitalized) sites").font(.footnote).foregroundStyle(Color.muted)
            }
            if model.atHome {
                SourceLine(text: "Your phone isn't in Philadelphia, so distances are from your home, \(model.home?.name ?? "your saved address").")
            } else if model.outsidePhilly {
                SourceLine(text: "You're outside Philadelphia, so distances are from City Hall.")
            }
            if open.isEmpty, let next = model.relevantSites.first {
                Text("The city lists \(model.relevantSites.count) \(model.sitesMode) sites. Nearest: \(next.name), \(next.hoursLine.lowerFirst).")
                    .font(.subheadline).foregroundStyle(Color.muted)
            }
            ForEach(Array(open)) { s in
                Button { selected = s } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.name).font(.headline).foregroundStyle(Color.ink).lineLimit(1)
                            Text("\(walk.label(s, model: model)) · \(s.hoursLine.lowerFirst)")
                                .font(.subheadline).foregroundStyle(Color.muted).multilineTextAlignment(.leading)
                        }
                        Spacer()
                        LevelPill(level: s.crowd.level, forecast: s.crowd.source == "swelter forecast")
                    }
                }
                .task(id: model.origin.coordinate.latitude) { walk.request(s, from: model.origin) }
            }
        }
        .padding(16)
        .background(.white, in: RoundedRectangle(cornerRadius: 20))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 2)
        .padding(.horizontal, 12).padding(.bottom, 8)
    }
}

struct AlertDetail: View {
    @Environment(AppModel.self) private var model
    @State private var speaking = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let live = model.live {
                        ForEach(live.alerts) { a in
                            Card {
                                Text(a.event).font(.title3.bold())
                                if let h = a.headline { Text(h).font(.subheadline.weight(.semibold)) }
                                if live.replay { Text(conditionsLine(live)).font(.subheadline) }
                                if !a.instruction.isEmpty { Text(a.instruction) }
                                Text(a.description).font(.callout).foregroundStyle(Color.muted)
                                SourceLine(text: a.source ?? "National Weather Service")
                                if model.config?.voice == true {
                                    Button {
                                        speaking = true
                                        Task {
                                            await model.speak([a.event, a.headline, a.instruction].compactMap { $0 }.joined(separator: ". "))
                                            speaking = false
                                        }
                                    } label: { Label(speaking ? "Loading…" : "Listen", systemImage: "speaker.wave.2.fill") }
                                }
                            }
                        }
                        if live.alerts.isEmpty && !live.replay {
                            Card { Text("No active NWS alerts for Philadelphia.") ; Text(conditionsLine(live)).foregroundStyle(Color.muted) }
                        }
                        if !live.forecast.isEmpty {
                            Card {
                                Text("Next hours").font(.headline)
                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 14) {
                                        ForEach(live.forecast.prefix(12), id: \.time) { h in
                                            VStack(spacing: 4) {
                                                Text(shortHour(h.time)).font(.caption).foregroundStyle(Color.muted)
                                                Text("\(h.tempF)°").font(.headline)
                                            }
                                        }
                                    }
                                }
                                SourceLine(text: "NWS hourly forecast")
                            }
                        }
                        if let c = live.conditions.aqiSource { SourceLine(text: "Air quality: \(c)") }
                    }
                }
                .padding(16)
            }
            .background(Color.bg)
            .navigationTitle("Conditions")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private func shortHour(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter().date(from: iso) else { return "" }
        return d.formatted(.dateTime.hour())
    }
}
