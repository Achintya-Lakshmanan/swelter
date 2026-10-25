import AVFoundation
import CoreLocation
import MapKit
import Observation
import SwiftUI

/// City Hall: where the map centres when the phone is outside Philadelphia (e.g. a simulator elsewhere).
let cityHall = CLLocationCoordinate2D(latitude: 39.9526, longitude: -75.1652)

func inPhilly(_ c: CLLocationCoordinate2D) -> Bool {
    (39.86...40.14).contains(c.latitude) && (-75.29 ... -74.95).contains(c.longitude)
}

@Observable
final class AppModel: NSObject, CLLocationManagerDelegate {
    // server data
    var config: AppConfig?
    var live: Live?
    var sites: [Site] = []
    var sitesMode = "cooling"
    var loadError: String?
    var loading = false

    // settings (stored)
    var spanish = UserDefaults.standard.bool(forKey: "spanish") { didSet { UserDefaults.standard.set(spanish, forKey: "spanish") } }
    /// Demo: replay one of the stored record days instead of today. Always labelled on screen.
    var replay: String? = UserDefaults.standard.string(forKey: "replay") { didSet { UserDefaults.standard.set(replay, forKey: "replay") } }
    /// A replay runs on the real clock: the record day's weather at the current hour.
    var clockHour = Calendar.current.component(.hour, from: Date())
    var replayHour: Int { clockHour }
    /// Hourly "are you okay?" check-ins while the weather is dangerous (on unless turned off).
    var checkInsOn = UserDefaults.standard.object(forKey: "checkInsOn") as? Bool ?? true {
        didSet { UserDefaults.standard.set(checkInsOn, forKey: "checkInsOn") }
    }
    /// Minutes to wait for an answer before asking a volunteer to check.
    var checkInWait = UserDefaults.standard.object(forKey: "checkInWait") as? Int ?? 5 {
        didSet { UserDefaults.standard.set(checkInWait, forKey: "checkInWait") }
    }
    /// Read request updates aloud ("Marisol accepted your request").
    var speakUpdates = UserDefaults.standard.object(forKey: "speakUpdates") as? Bool ?? true {
        didSet { UserDefaults.standard.set(speakUpdates, forKey: "speakUpdates") }
    }
    var checkIn: CheckInPrompt?
    var residentTab = 0
    /// Set when the resident sends a request from the form, so the status screen says it out loud once.
    var announceSent = false
    var crowdCounting = UserDefaults.standard.bool(forKey: "crowdCounting") {
        didSet { UserDefaults.standard.set(crowdCounting, forKey: "crowdCounting"); updateGeofences() }
    }

    // resident's open help request
    var activeRequest: (id: String, secret: String)? = {
        guard let id = UserDefaults.standard.string(forKey: "reqId"), let s = UserDefaults.standard.string(forKey: "reqSecret") else { return nil }
        return (id, s)
    }() {
        didSet {
            UserDefaults.standard.set(activeRequest?.id, forKey: "reqId")
            UserDefaults.standard.set(activeRequest?.secret, forKey: "reqSecret")
        }
    }

    // who's signed in (resident or responder)
    var account: Me?
    var restoring = true
    var responderMode: Bool { account?.isResponder == true }
    var name: String? { account?.profile?.name }
    var home: Me.Home? { account?.profile?.home }

    // location
    let manager = CLLocationManager()
    var here: CLLocation?
    var authStatus: CLAuthorizationStatus = .notDetermined
    var hereInPhilly: CLLocation? { here.flatMap { inPhilly($0.coordinate) ? $0 : nil } }
    var homeLocation: CLLocation? { home.map { CLLocation(latitude: $0.lat, longitude: $0.lon) } }
    /// Where distances and help requests start: the phone if it's in Philadelphia, else the saved home address.
    var origin: CLLocation {
        hereInPhilly ?? homeLocation ?? CLLocation(latitude: cityHall.latitude, longitude: cityHall.longitude)
    }
    /// The phone is elsewhere (or has no fix) and the app is using the saved home address.
    var atHome: Bool { hereInPhilly == nil && home != nil && (here != nil || authStatus == .denied) }
    var outsidePhilly: Bool { hereInPhilly == nil && home == nil && here != nil }
    /// Where a help request is sent from, if anywhere.
    var helpLocation: CLLocation? { hereInPhilly ?? (here != nil || authStatus == .denied ? homeLocation : nil) }

    private var player: AVAudioPlayer?
    private let synth = AVSpeechSynthesizer()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        authStatus = manager.authorizationStatus
    }

    func start() {
        if authStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
        manager.startUpdatingLocation()
        API.shared.bearer = Keychain.get("auth0")
        API.shared.demoAccount = UserDefaults.standard.string(forKey: "demoAccount")
        Task {
            if API.shared.bearer != nil || API.shared.demoAccount != nil { await loadAccount() }
            restoring = false
            await refresh()
        }
        Task { await followClock() }
    }

    /// When the hour turns, reload so conditions, open sites and crowd levels move with the clock.
    @MainActor
    private func followClock() async {
        while true {
            try? await Task.sleep(for: .seconds(30))
            let h = Calendar.current.component(.hour, from: Date())
            if h != clockHour {
                clockHour = h
                await refresh()
            }
        }
    }

    // MARK: sign-in

    @MainActor
    func loadAccount() async {
        do {
            account = try await API.shared.me()
        } catch {
            signOut()  // expired or revoked token: back to the sign-in screen
            loadError = error.localizedDescription
        }
    }

    @MainActor
    func signIn(demo id: String) async {
        activeRequest = nil
        API.shared.bearer = nil
        API.shared.demoAccount = id
        UserDefaults.standard.set(id, forKey: "demoAccount")
        await loadAccount()
    }

    @MainActor
    func signIn(token: String) async {
        activeRequest = nil
        API.shared.demoAccount = nil
        API.shared.bearer = token
        Keychain.set(token, "auth0")
        await loadAccount()
    }

    func signOut() {
        account = nil
        activeRequest = nil
        API.shared.bearer = nil
        API.shared.demoAccount = nil
        Keychain.set(nil, "auth0")
        UserDefaults.standard.removeObject(forKey: "demoAccount")
        ResponderData.shared.reset()
    }

    @MainActor
    func refresh() async {
        loading = true
        defer { loading = false }
        do {
            if config == nil { config = try await API.shared.config() }
            async let l = API.shared.live(replay: replay, hour: replayHour, spanish: spanish)
            async let s = API.shared.sites(replay: replay, hour: replayHour)
            let (lv, st) = try await (l, s)
            live = lv
            sites = st.sites
            sitesMode = st.mode
            loadError = nil
            updateGeofences()
            maybeCheckIn()
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// Sites for the current season/hazard, open ones first, nearest first.
    var relevantSites: [Site] {
        sites.filter { sitesMode == "warming" ? ($0.warming ?? false) : ($0.cooling ?? false) }
            .sorted { ($0.openNow ? 0 : 1, distance(to: $0)) < ($1.openNow ? 0 : 1, distance(to: $1)) }
    }

    func distance(to s: Site) -> CLLocationDistance { origin.distance(from: s.location) }

    // MARK: voice (ElevenLabs via the server)

    /// ElevenLabs through the server; the phone's own voice if the server has no key or can't be reached.
    /// Plays even with the ringer switch on silent.
    @MainActor
    func speak(_ text: String) async {
        player?.stop()
        synth.stopSpeaking(at: .immediate)
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        if config?.voice == true, let data = try? await API.shared.speak(text), let p = try? AVAudioPlayer(data: data) {
            player = p
            p.play()
        } else {
            synth.speak(AVSpeechUtterance(string: text))
        }
    }

    // MARK: location + crowd counting

    func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        authStatus = m.authorizationStatus
        if authStatus == .authorizedWhenInUse || authStatus == .authorizedAlways { m.startUpdatingLocation() }
        updateGeofences()
    }

    func locationManager(_ m: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        let first = here == nil
        here = locs.last
        if first { updateGeofences() }
    }

    func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {}

    /// A random code for today only, so the server can count distinct phones without knowing which phone.
    var dailyToken: String {
        let day = Date().formatted(.iso8601.year().month().day())
        if UserDefaults.standard.string(forKey: "tokenDay") != day {
            UserDefaults.standard.set(day, forKey: "tokenDay")
            UserDefaults.standard.set(UUID().uuidString, forKey: "token")
        }
        return UserDefaults.standard.string(forKey: "token")!
    }

    /// iOS watches at most 20 regions: the 20 nearest open sites, 60 m around each.
    func updateGeofences() {
        for r in manager.monitoredRegions { manager.stopMonitoring(for: r) }
        guard crowdCounting else { return }
        if manager.authorizationStatus != .authorizedAlways {
            manager.requestAlwaysAuthorization()
            return
        }
        for s in relevantSites.filter(\.openNow).prefix(20) {
            let r = CLCircularRegion(center: s.coordinate, radius: 60, identifier: s.id)
            r.notifyOnEntry = true
            r.notifyOnExit = true
            manager.startMonitoring(for: r)
        }
    }

    func locationManager(_ m: CLLocationManager, didEnterRegion region: CLRegion) { send(region.identifier, "enter") }
    func locationManager(_ m: CLLocationManager, didExitRegion region: CLRegion) { send(region.identifier, "exit") }

    private func send(_ site: String, _ event: String) {
        guard crowdCounting else { return }
        let token = dailyToken
        Task { try? await API.shared.presence(site: site, event: event, token: token) }
    }
}
