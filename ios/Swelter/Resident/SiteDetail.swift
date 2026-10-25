import Charts
import MapKit
import SwiftUI

struct SiteDetail: View {
    @Environment(AppModel.self) private var model
    let site: Site
    var canReport = false  // volunteers report how busy it is from here
    @State private var walk = WalkTimes.shared
    @State private var reporting = false
    @State private var sent: String?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ReplayBanner()
                VStack(alignment: .leading, spacing: 4) {
                    Text(site.type.isEmpty ? "\(model.sitesMode.capitalized) site" : site.type)
                        .font(.footnote.weight(.semibold)).foregroundStyle(Color.muted)
                    Text(site.name).font(.largeTitle.bold()).foregroundStyle(Color.ink)
                    Text(site.address).foregroundStyle(Color.muted)
                }
                HStack {
                    LevelPill(level: site.openNow ? site.crowd.level : nil, forecast: site.openNow && site.crowd.source == "swelter forecast")
                    Text(site.hoursLine).font(.subheadline.weight(.semibold))
                }
                CrowdCard(site: site)
                if canReport {
                    PrimaryButton(title: sent.map { "Reported \($0) · thank you" } ?? "Report how busy it is", color: .ink) { reporting = true }
                }
                if let h = site.hoursText {
                    Card {
                        Text("Hours").font(.headline)
                        Text(h)
                        SourceLine(text: "Posted by the city")
                    }
                }
                Amenities(site: site)
                VStack(spacing: 10) {
                    PrimaryButton(title: "Walk there · \(walk.label(site, model: model))") { openMaps() }
                    if let p = site.phone, let url = URL(string: "tel:\(p.filter(\.isNumber))") {
                        Link(destination: url) {
                            Text("Call the site · \(p)").font(.headline).frame(maxWidth: .infinity, minHeight: 50)
                                .background(.white, in: RoundedRectangle(cornerRadius: 14))
                        }
                    }
                }
                SourceLine(text: site.source)
            }
            .padding(16)
        }
        .background(Color.bg)
        .navigationBarTitleDisplayMode(.inline)
        .task(id: model.origin.coordinate.latitude) { walk.request(site, from: model.origin) }
        .confirmationDialog("How busy is \(site.name)?", isPresented: $reporting, titleVisibility: .visible) {
            ForEach(["quiet", "busy", "full"], id: \.self) { lv in
                Button(LevelStyle.of(lv).label) { report(lv) }
            }
        }
        .alert("Couldn't send the report", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {} message: { Text(error ?? "") }
    }

    private func report(_ level: String) {
        Task {
            do {
                try await API.shared.report(site: site.id, level: level)
                sent = LevelStyle.of(level).label.lowercased()
                await model.refresh()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func openMaps() {
        let item = MKMapItem(placemark: MKPlacemark(coordinate: site.coordinate))
        item.name = site.name
        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeWalking])
    }
}

struct CrowdCard: View {
    @Environment(AppModel.self) private var model
    let site: Site

    var body: some View {
        let c = site.crowd
        Card {
            Text("How busy it is").font(.headline)
            switch c.source {
            case "site lead":
                Text("The site lead reported **\(LevelStyle.of(c.level).label.lowercased())** \(c.minutesAgo ?? 0) minutes ago.")
            case "phones":
                if let cap = site.capacity {
                    Text("\(c.phonesInside ?? 0) phones with ChillySOS are inside now. The city lists room for \(cap).")
                } else {
                    Text("\(c.phonesInside ?? 0) phones with ChillySOS are inside now. The city doesn't list this site's capacity, so there's no level.")
                }
            case "swelter forecast":
                if let by = c.byHour, let hours = c.hours {
                    Chart {
                        ForEach(Array(zip(hours, by)), id: \.0) { h, n in
                            BarMark(x: .value("Hour", h), y: .value("People", n))
                                .foregroundStyle(h == currentHour ? LevelStyle.of(c.level).pin : Color(hex: 0xC9D2D8))
                        }
                    }
                    .chartXAxis { AxisMarks(values: [9, 12, 15, 18, 21]) { v in AxisValueLabel { Text(hourLabel(v.as(Int.self) ?? 0)) } } }
                    .chartYAxis(.hidden)
                    .frame(height: 110)
                    if !hours.contains(currentHour) {
                        Text("ChillySOS simulates \(hourLabel(hours.first ?? 6)) to \(hourLabel(hours.last ?? 22)), so there's no forecast for \(hourLabel(currentHour)).")
                    }
                    if let b = c.busiestHour { Text("Usually busiest around \(hourLabel(b)) on days like this.") }
                    SourceLine(text: "ChillySOS simulation of \(c.realDay ?? "a real day on record") with the city's sites open. Synthetic residents, not a head count.")
                }
            default:
                Text("No one has reported how busy it is. Crowd levels appear when a site lead reports, or when \(model.config?.kMin ?? 5) or more phones with crowd counting have been here.")
                    .foregroundStyle(Color.muted)
            }
        }
    }

    private var currentHour: Int {
        model.clockHour
    }
}

/// Only what the city's layer actually says about the site.
struct Amenities: View {
    let site: Site
    var body: some View {
        let items: [(String, String)] = [
            site.water == true ? ("drop.fill", "Water station") : nil,
            site.accessible == true ? ("figure.roll", "Accessible entrance") : nil,
            site.accessible == false ? ("exclamationmark.triangle", "Not listed as accessible") : nil,
        ].compactMap { $0 }
        if !items.isEmpty || site.services != nil || site.facilities != nil {
            Card {
                Text("What's here").font(.headline)
                ForEach(items, id: \.1) { icon, label in Label(label, systemImage: icon) }
                if let s = site.services { Text(s).font(.callout) }
                if let f = site.facilities { Text(f).font(.callout).foregroundStyle(Color.muted) }
                SourceLine(text: "From the city's site listing")
            }
        }
    }
}
