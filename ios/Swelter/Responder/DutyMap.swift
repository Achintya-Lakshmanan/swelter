import MapKit
import SwiftUI

struct DutyMap: View {
    @Environment(AppModel.self) private var model
    @State private var data = ResponderData.shared
    @State private var camera: MapCameraPosition = .region(MKCoordinateRegion(center: cityHall, latitudinalMeters: 6000, longitudinalMeters: 6000))
    @State private var showRisk = true
    @State private var showSites = true
    @State private var open: HelpRequest?
    @State private var site: Site?

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Map(position: $camera) {
                    UserAnnotation()
                    if showRisk, let g = data.risk, let step = g.step {
                        ForEach(g.cells, id: \.key) { c in  // stable ids: an hour change updates cells instead of rebuilding all
                            MapPolygon(coordinates: square(c, step))
                                .foregroundStyle(riskColor(c.danger).opacity(0.38))
                        }
                    }
                    if showSites {
                        ForEach(model.relevantSites.filter(\.openNow)) { s in
                            Annotation(s.name, coordinate: s.coordinate) {
                                Button { site = s } label: { SitePin(site: s) }  // opens how busy it is, hours, report
                            }
                            .annotationTitles(.hidden)
                        }
                    }
                    ForEach(data.requests) { r in
                        if let c = r.coordinate {
                            Annotation(Labels.need(r.need), coordinate: c) {
                                Button { open = r } label: { RequestPin(r: r) }
                            }
                            .annotationTitles(.hidden)
                        }
                    }
                }
                .mapControls { MapUserLocationButton() }

                VStack(spacing: 8) {
                    ResponderHeader()
                        .padding(12).background(.white, in: RoundedRectangle(cornerRadius: 16))
                    ReplayBanner()
                    HStack(spacing: 8) {
                        MapChip(title: riskLabel, icon: "flame.fill", on: $showRisk)
                        MapChip(title: "Sites", icon: "building.columns.fill", on: $showSites)
                        Spacer()
                    }
                }
                .padding(.horizontal, 12).padding(.top, 4)
            }
            .safeAreaInset(edge: .bottom) { urgentCard }
            .navigationDestination(item: $open) { RequestDetail(request: $0) }
            .navigationDestination(item: $site) { SiteDetail(site: $0, canReport: true) }
            .toolbar(.hidden, for: .navigationBar)
            .onAppear {
                camera = .region(MKCoordinateRegion(center: model.origin.coordinate, latitudinalMeters: 4000, longitudinalMeters: 4000))
            }
        }
    }

    private var riskLabel: String {
        guard let g = data.risk, let h = g.hour else { return "Swelter risk" }
        return g.simulated == false ? "Swelter risk · none at \(hourLabel(h))" : "Swelter risk · \(hourLabel(h))"
    }

    @ViewBuilder private var urgentCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let e = data.error {
                Text(e).font(.subheadline).foregroundStyle(Color.danger)
            } else if let r = data.sorted.first {
                Text(r.mine == true ? "You accepted" : "Most urgent · waiting \(r.minutesWaiting ?? 0) min")
                    .font(.footnote.weight(.semibold)).foregroundStyle(Color.muted)
                Button { open = r } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(headline(r)).font(.headline).foregroundStyle(Color.ink)
                        Text(whoLine(r)).font(.subheadline).foregroundStyle(Color.muted).multilineTextAlignment(.leading)
                    }
                }
                Text("\(data.requests.count) open request\(data.requests.count == 1 ? "" : "s")").font(.footnote).foregroundStyle(Color.muted)
            } else {
                Text("No open requests right now").font(.headline)
                SourceLine(text: "Requests appear here when residents ask for help in the app.")
            }
            if showRisk, let g = data.risk { SourceLine(text: g.note) }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 20))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 2)
        .padding(.horizontal, 12).padding(.bottom, 8)
    }

    private func square(_ c: RiskGrid.Cell, _ step: Double) -> [CLLocationCoordinate2D] {
        let h = step / 2
        return [.init(latitude: c.lat - h, longitude: c.lon - h), .init(latitude: c.lat - h, longitude: c.lon + h),
                .init(latitude: c.lat + h, longitude: c.lon + h), .init(latitude: c.lat + h, longitude: c.lon - h)]
    }

    private func riskColor(_ n: Int) -> Color {
        n >= 8 ? Color(hex: 0xB3261E) : n >= 3 ? Color(hex: 0xC2410C) : Color(hex: 0xD08A00)
    }
}

/// A layer switch that stays readable on any map: solid white when off, dark when on.
struct MapChip: View {
    let title: String
    let icon: String
    @Binding var on: Bool

    var body: some View {
        Button { on.toggle() } label: {
            Label(title, systemImage: on ? icon : "eye.slash")
                .font(.footnote.weight(.semibold))
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(on ? Color.ink : .white, in: Capsule())
                .foregroundStyle(on ? .white : Color.ink)
                .overlay(Capsule().stroke(Color.ink.opacity(on ? 0 : 0.25), lineWidth: 1))
                .shadow(color: .black.opacity(0.18), radius: 6, y: 2)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// "Kayla · Check on someone" when a signed-in resident asked.
func headline(_ r: HelpRequest) -> String {
    [r.name, Labels.need(r.need)].compactMap { $0 }.joined(separator: " · ")
}

func whoLine(_ r: HelpRequest) -> String {
    ([(r.people ?? 1) == 1 ? "1 person" : "\(r.people ?? 1) people"] + r.flags.map { Labels.flag($0) })
        .joined(separator: " · ")
}

struct RequestPin: View {
    let r: HelpRequest
    var body: some View {
        VStack(spacing: 2) {
            Text("\(r.minutesWaiting ?? 0)m")
                .font(.caption.weight(.bold))
                .padding(.horizontal, 7).padding(.vertical, 4)
                .background(r.mine == true ? Color.action : Color.danger, in: Capsule())
                .foregroundStyle(.white)
            if r.exact == false {
                Circle().stroke(Color.danger.opacity(0.5), style: StrokeStyle(lineWidth: 1.5, dash: [3]))
                    .frame(width: 26, height: 26)
            }
        }
        .accessibilityLabel("\(Labels.need(r.need)), waiting \(r.minutesWaiting ?? 0) minutes")
    }
}
