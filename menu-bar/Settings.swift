import AppKit
import SwiftUI

struct AppSettings: Codable {
    var language = "en"
    var theme = "system"
    var showContext = true
    var showBreakdown = true
    var showLocalUsage = true
    var showTrend = true
    var showAdvanced = false
    var accent = "cyan"

    init() {}

    private enum CodingKeys: String, CodingKey {
        case language, theme, showContext, showBreakdown, showLocalUsage, showTrend, showAdvanced, accent
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        language = (try? c.decode(String.self, forKey: .language)) == "zh" ? "zh" : "en"
        let savedTheme = try? c.decode(String.self, forKey: .theme)
        theme = ["system", "dark", "light"].contains(savedTheme ?? "") ? savedTheme! : "system"
        showContext = (try? c.decode(Bool.self, forKey: .showContext)) ?? true
        showBreakdown = (try? c.decode(Bool.self, forKey: .showBreakdown)) ?? true
        showLocalUsage = (try? c.decode(Bool.self, forKey: .showLocalUsage)) ?? true
        showTrend = (try? c.decode(Bool.self, forKey: .showTrend)) ?? true
        showAdvanced = (try? c.decode(Bool.self, forKey: .showAdvanced)) ?? false
        let savedAccent = try? c.decode(String.self, forKey: .accent)
        accent = ["cyan", "violet", "green"].contains(savedAccent ?? "") ? savedAccent! : "cyan"
    }
}

enum SettingsStore {
    static let path = ProcessInfo.processInfo.environment["CODEX_DASHBOARD_PREFERENCES"]
        .map { URL(fileURLWithPath: $0) } ?? FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".codex/codex-dashboard/preferences.json")

    static func load() -> AppSettings {
        guard let data = try? Data(contentsOf: path) else { return AppSettings() }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return (try? decoder.decode(AppSettings.self, from: data)) ?? AppSettings()
    }

    static func save(_ value: AppSettings) {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        guard let data = try? encoder.encode(value) else { return }
        try? FileManager.default.createDirectory(at: path.deletingLastPathComponent(),
                                                  withIntermediateDirectories: true)
        try? data.write(to: path, options: .atomic)
    }
}

struct PulsePalette {
    let bg: Color
    let panel: Color
    let border: Color
    let muted: Color
    let cyan: Color
    let violet: Color
    let lime: Color
    let text: Color
    let track: Color

    init(light: Bool, accent: String = "cyan") {
        bg = light ? Color(red: 0.95, green: 0.97, blue: 0.99) : Color(red: 0.035, green: 0.055, blue: 0.105)
        panel = light ? .white : Color(red: 0.075, green: 0.105, blue: 0.17)
        border = light ? .black.opacity(0.1) : .white.opacity(0.11)
        muted = light ? Color(red: 0.34, green: 0.42, blue: 0.52) : Color(red: 0.60, green: 0.68, blue: 0.80)
        text = light ? Color(red: 0.08, green: 0.13, blue: 0.20) : .white
        track = light ? .black.opacity(0.08) : .white.opacity(0.09)
        violet = light ? Color(red: 0.42, green: 0.26, blue: 0.72) : Color(red: 0.69, green: 0.52, blue: 1)
        lime = light ? Color(red: 0.13, green: 0.48, blue: 0.32) : Color(red: 0.63, green: 0.96, blue: 0.68)
        switch accent {
        case "violet": cyan = violet
        case "green": cyan = lime
        default: cyan = light ? Color(red: 0, green: 0.46, blue: 0.58) : Color(red: 0.29, green: 0.91, blue: 0.95)
        }
    }
}

private struct PaletteKey: EnvironmentKey {
    static let defaultValue = PulsePalette(light: false)
}

extension EnvironmentValues {
    var pulsePalette: PulsePalette {
        get { self[PaletteKey.self] }
        set { self[PaletteKey.self] = newValue }
    }
}
