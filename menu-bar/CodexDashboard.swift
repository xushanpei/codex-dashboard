import AppKit
import SwiftUI

private func modelVisual(_ model: String?, language: String = "en") -> (symbol: String, color: Color, label: String) {
    let name = model?.lowercased() ?? ""
    let zh = language == "zh"
    if name.contains("astra") { return ("sparkles", Color(red: 0.83, green: 0.67, blue: 1), zh ? "群星" : "Stars") }
    if name.contains("sol") { return ("sun.max.fill", Color(red: 1, green: 0.77, blue: 0.36), zh ? "太阳" : "Sun") }
    if name.contains("terra") { return ("globe.europe.africa.fill", Color(red: 0.61, green: 0.91, blue: 0.57), zh ? "大地" : "Earth") }
    if name.contains("luna") { return ("moon.fill", Color(red: 0.68, green: 0.78, blue: 1), zh ? "月亮" : "Moon") }
    return ("cpu.fill", .gray, zh ? "模型" : "Model")
}

private struct Usage: Decodable {
    let inputTokens: Int
    let cachedInputTokens: Int
    let cacheWriteInputTokens: Int
    let outputTokens: Int
    let reasoningOutputTokens: Int
    let totalTokens: Int
}

private struct RateLimit: Decodable {
    let usedPercent: Double?
    let windowMinutes: Int?
    let windowDurationMins: Int?
    let resetsAt: Int?
    var minutes: Int? { windowDurationMins ?? windowMinutes }
}

private struct AccountLimits: Decodable {
    let primary: RateLimit?
    let secondary: RateLimit?
    let credits: CreditInfo?
}

private struct RateLimitBucket: Decodable {
    let limitName: String?
    let primary: RateLimit?
    let secondary: RateLimit?
    let credits: CreditInfo?
}

private struct ResetCredit: Decodable {
    let title: String?
    let status: String?
    let expiresAt: Int?
}

private struct ResetCredits: Decodable {
    let availableCount: Int?
    let credits: [ResetCredit]?
}

private struct Account: Decodable {
    let email: String?
    let displayName: String?
    let planType: String?
    let authType: String?
    let rateLimits: AccountLimits?
    let rateLimitsByLimitId: [String: RateLimitBucket]?
    let rateLimitResetCredits: ResetCredits?
    let stale: Bool?
}

private struct QuotaWindow: Identifiable {
    let id: String
    let title: String
    let durationMinutes: Int?
    let remaining: Double?
    let resetsAt: Int?
}

private func quotaWindowLabel(_ minutes: Int?, language: String) -> String {
    let english = language == "en"
    guard let minutes, minutes > 0 else { return english ? "Quota window" : "额度窗口" }
    if minutes % 10_080 == 0 { return english ? "\(minutes / 10_080)-week quota" : "\(minutes / 10_080) 周额度" }
    if minutes % 1_440 == 0 { return english ? "\(minutes / 1_440)-day quota" : "\(minutes / 1_440) 天额度" }
    if minutes % 60 == 0 { return english ? "\(minutes / 60)-hour quota" : "\(minutes / 60) 小时额度" }
    return english ? "\(minutes)-minute quota" : "\(minutes) 分钟额度"
}

private func quotaWindows(_ account: Account?, language: String = "en") -> [QuotaWindow] {
    guard let account, account.stale != true,
          account.authType != "apiKey", account.authType != "amazonBedrock" else { return [] }
    var windows: [QuotaWindow] = []
    func add(_ rate: RateLimit?, id: String, prefix: String) {
        guard let rate else { return }
        windows.append(QuotaWindow(
            id: id, title: prefix + quotaWindowLabel(rate.minutes, language: language), durationMinutes: rate.minutes,
            remaining: rate.usedPercent.map { min(100, max(0, 100 - $0)) }, resetsAt: rate.resetsAt))
    }
    if let buckets = account.rateLimitsByLimitId, !buckets.isEmpty {
        for (id, bucket) in buckets.sorted(by: { $0.key < $1.key }) {
            let label = bucket.limitName.flatMap { $0.isEmpty ? nil : $0 } ?? id
            let name = id == "codex" ? "" : "\(label) · "
            add(bucket.primary, id: "\(id)-primary", prefix: name)
            add(bucket.secondary, id: "\(id)-secondary", prefix: name)
        }
    } else {
        add(account.rateLimits?.primary, id: "legacy-primary", prefix: "")
        add(account.rateLimits?.secondary, id: "legacy-secondary", prefix: "")
    }
    return windows.sorted { ($0.durationMinutes ?? Int.max, $0.title) < ($1.durationMinutes ?? Int.max, $1.title) }
}

private struct CreditInfo: Decodable {
    let hasCredits: Bool?
    let unlimited: Bool?
    let balance: String?

    private enum CodingKeys: String, CodingKey { case hasCredits, unlimited, balance }

    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        hasCredits = try fields.decodeIfPresent(Bool.self, forKey: .hasCredits)
        unlimited = try fields.decodeIfPresent(Bool.self, forKey: .unlimited)
        if let text = try? fields.decode(String.self, forKey: .balance) {
            balance = text
        } else if let number = try? fields.decode(Double.self, forKey: .balance) {
            balance = String(format: "%.2f", number)
        } else {
            balance = nil
        }
    }
}

private struct Session: Decodable, Identifiable {
    let id: String
    let title: String?
    let updatedAt: String?
    let startedAt: String?
    let cwd: String?
    let originator: String?
    let provider: String?
    let model: String?
    let effort: String?
    let taskStatus: String?
    let turnStartedAt: Int?
    let lastDurationMs: Int?
    let contextWindow: Int?
    let lastInputTokens: Int?
    let lastCachedTokens: Int?
    let usage: Usage
    let rateLimit: RateLimit?
}

private struct DailyPoint: Decodable, Identifiable {
    let date: String
    let totalTokens: Int
    var id: String { date }
}

private struct RuntimeSignal: Decodable {
    let at: String?
    let from: String?
    let to: String?
    let source: String?
}

private struct RuntimeSignals: Decodable {
    let modelChange: RuntimeSignal?
    let effortReduction: RuntimeSignal?
    let observedEvents: Int?
}

private struct Snapshot: Decodable {
    let currentSession: Session?
    let selectionMode: String?
    let recentSessions: [Session]
    let today: Usage
    let thisWeek: Usage
    let thisMonth: Usage
    let sevenDays: Usage
    let dailyUsage: [DailyPoint]
    let monthDailyUsage: [DailyPoint]
    let historyDailyUsage: [DailyPoint]?
    let runtimeSignals: RuntimeSignals?
    let updatedAt: String
    let availableSessions: [SessionChoice]
    let account: Account?
}

private struct UpdateInfo: Decodable {
    let available: Bool
    let latestVersion: String
    let releaseUrl: String
}

private struct SessionChoice: Decodable, Identifiable {
    let id: String
    let title: String
}

private final class DashboardModel: ObservableObject {
    @Published var snapshot: Snapshot?
    @Published var error: String?
    @Published var statusIcon: NSImage?
    @Published var updateInfo: UpdateInfo?
    @Published var updateMessage: String?
    @Published var settings = SettingsStore.load() {
        didSet { SettingsStore.save(settings) }
    }
    @Published var settingsMessage: String?
}

private final class StatusIconRenderer {
    private let source: CGImage?
    private var cache: [String: NSImage] = [:]

    init() {
        let path = Bundle.main.resourceURL!.appendingPathComponent("codex-mark.png")
        source = NSImage(contentsOf: path)?.cgImage(forProposedRect: nil, context: nil, hints: nil)
    }

    func image(for state: String) -> NSImage? {
        if let cached = cache[state] { return cached }
        guard let source else { return nil }
        let width = source.width, height = source.height
        let rowBytes = width * 4
        var pixels = [UInt8](repeating: 0, count: rowBytes * height)
        let tint: (UInt8, UInt8, UInt8)?
        switch state {
        case "running": tint = (190, 255, 80)
        case "unconfirmed": tint = (255, 190, 70)
        case "error": tint = (255, 104, 120)
        default: tint = nil
        }
        let rendered = pixels.withUnsafeMutableBytes { storage -> CGImage? in
            guard let context = CGContext(data: storage.baseAddress, width: width, height: height,
                                          bitsPerComponent: 8, bytesPerRow: rowBytes,
                                          space: CGColorSpaceCreateDeviceRGB(),
                                          bitmapInfo: CGBitmapInfo.byteOrder32Big.rawValue | CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
            context.draw(source, in: CGRect(x: 0, y: 0, width: width, height: height))
            if let (red, green, blue) = tint {
                for y in Int(Double(height) * 0.34)..<Int(Double(height) * 0.72) {
                    for x in Int(Double(width) * 0.25)..<Int(Double(width) * 0.75) {
                        let i = y * rowBytes + x * 4
                        let r = Int(storage[i]), g = Int(storage[i + 1]), b = Int(storage[i + 2])
                        let a = Int(storage[i + 3])
                        if a >= 100 && min(r, g, b) >= 160 && max(r, g, b) - min(r, g, b) <= 42 {
                            let shade = Double(min(r, g, b)) / 255.0
                            storage[i] = UInt8(Double(red) * shade)
                            storage[i + 1] = UInt8(Double(green) * shade)
                            storage[i + 2] = UInt8(Double(blue) * shade)
                        }
                    }
                }
            }
            return context.makeImage()
        }
        guard let rendered else { return nil }
        let crop = CGRect(x: CGFloat(width) * 0.12, y: CGFloat(height) * 0.15,
                          width: CGFloat(width) * 0.76, height: CGFloat(height) * 0.76)
        guard let cropped = rendered.cropping(to: crop) else { return nil }
        let base = NSImage(cgImage: cropped, size: NSSize(width: 22, height: 22))
        let icon = NSImage(size: NSSize(width: 22, height: 22), flipped: false) { rect in
            base.draw(in: rect)
            if let (red, green, blue) = tint {
                let badge = NSBezierPath(ovalIn: NSRect(x: 15.5, y: 0.5, width: 6.5, height: 6.5))
                NSColor(deviceRed: CGFloat(red) / 255, green: CGFloat(green) / 255,
                        blue: CGFloat(blue) / 255, alpha: 1).setFill()
                badge.fill()
            }
            return true
        }
        cache[state] = icon
        return icon
    }
}

private func compact(_ number: Int) -> String {
    if number >= 1_000_000_000 { return String(format: "%.2fB", Double(number) / 1_000_000_000) }
    if number >= 1_000_000 { return String(format: "%.2fM", Double(number) / 1_000_000) }
    if number >= 10_000 { return String(format: "%.1fk", Double(number) / 1_000) }
    return number.formatted()
}

private func clock(_ stamp: String?) -> String {
    guard let date = parseDate(stamp) else { return "—" }
    return date.formatted(date: .omitted, time: .shortened)
}

private func parseDate(_ stamp: String?) -> Date? {
    guard let stamp else { return nil }
    let parser = ISO8601DateFormatter()
    parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let date = parser.date(from: stamp) ?? ISO8601DateFormatter().date(from: stamp)
    return date
}

private func resetTime(_ epoch: Int?, language: String = "en") -> String {
    guard let epoch else { return "—" }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: language == "zh" ? "zh_CN" : "en_US")
    formatter.dateStyle = .medium
    formatter.timeStyle = .short
    return formatter.string(from: Date(timeIntervalSince1970: TimeInterval(epoch)))
}

private func duration(_ milliseconds: Int, language: String = "en") -> String {
    let seconds = max(0, milliseconds / 1000)
    if language == "zh" {
        if seconds >= 3600 { return "\(seconds / 3600) 小时 \((seconds % 3600) / 60) 分" }
        if seconds >= 60 { return "\(seconds / 60) 分 \(seconds % 60) 秒" }
        return "\(seconds) 秒"
    }
    if seconds >= 3600 { return "\(seconds / 3600)h \((seconds % 3600) / 60)m" }
    if seconds >= 60 { return "\(seconds / 60)m \(seconds % 60)s" }
    return "\(seconds)s"
}

private struct GlassCard<Content: View>: View {
    @Environment(\.pulsePalette) private var palette
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) { content }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(palette.panel.opacity(0.96), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(palette.border, lineWidth: 1))
    }
}

private struct MeterBar: View {
    @Environment(\.pulsePalette) private var palette
    let fraction: Double
    let tint: Color
    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(palette.track)
                Capsule().fill(LinearGradient(colors: [tint, tint.opacity(0.55)], startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(4, geometry.size.width * min(max(fraction, 0), 1)))
            }
        }
        .frame(height: 7)
    }
}

private struct MetricCard: View {
    @Environment(\.pulsePalette) private var palette
    let label: String
    let value: String
    let icon: String
    let tint: Color
    var body: some View {
        return GlassCard {
            HStack {
                Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(palette.muted)
                Spacer()
                Image(systemName: icon).foregroundStyle(tint)
            }
            Text(value).font(.system(size: 25, weight: .semibold, design: .rounded))
                .foregroundStyle(palette.text).minimumScaleFactor(0.7).lineLimit(1)
            Text("TOKENS").font(.system(size: 9, weight: .bold, design: .monospaced))
                .tracking(1.5).foregroundStyle(tint)
        }
    }
}

private struct DashboardView: View {
    @Environment(\.colorScheme) private var systemColorScheme
    @ObservedObject var model: DashboardModel
    @State private var trendPeriod = 7
    @State private var showResetDetails = false
    @State private var hoveredDay: DailyPoint?
    private let horizontalInset: CGFloat = 20
    let refresh: () -> Void
    let checkUpdate: () -> Void
    let installUpdate: () -> Void
    let openSettings: () -> Void
    let quit: () -> Void

    private var theme: PulsePalette {
        let light = model.settings.theme == "light" ||
            (model.settings.theme == "system" && systemColorScheme == .light)
        return PulsePalette(light: light, accent: model.settings.showAdvanced ? model.settings.accent : "cyan")
    }

    private func t(_ english: String, _ chinese: String) -> String {
        model.settings.language == "zh" ? chinese : english
    }

    private var current: Session? { model.snapshot?.currentSession }
    private var isRunning: Bool { current?.taskStatus == "running" }
    private var statusLabel: String {
        guard current != nil else { return t("No activity", "暂无记录") }
        switch current?.taskStatus {
        case "running": return t("Running", "运行中")
        case "unconfirmed": return t("Unconfirmed", "状态待确认")
        default: return t("Idle", "空闲")
        }
    }

    var body: some View {
        ZStack {
            theme.bg
            Circle().fill(theme.cyan.opacity(0.14)).frame(width: 290, height: 290).blur(radius: 90).offset(x: 150, y: -260)
            Circle().fill(theme.violet.opacity(0.15)).frame(width: 220, height: 220).blur(radius: 80).offset(x: -170, y: 160)
            GeometryReader { geometry in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header
                        if let update = model.updateInfo, update.available { updateCard(update) }
                        accountOverview
                        sectionHeader(model.snapshot?.selectionMode == "desktop_view" ? t("Current chat", "当前会话") : t("Recent chat", "最近会话"),
                                      detail: model.snapshot?.selectionMode == "desktop_view" ? t("This chat only", "仅当前聊天") : t("By recent activity", "按最近活动"),
                                      icon: "bubble.left.fill", tint: theme.cyan)
                        hero
                        if model.settings.showContext { contextCard }
                        if model.settings.showBreakdown { breakdownCard }
                        if let snapshot = model.snapshot {
                            if model.settings.showLocalUsage {
                                sectionHeader(t("On this device", "本机统计"), detail: t("All signed-in accounts", "所有登录账号"), icon: "desktopcomputer", tint: theme.violet)
                                HStack(spacing: 10) {
                                    MetricCard(label: t("Today", "今日"), value: compact(snapshot.today.totalTokens), icon: "sun.max.fill", tint: theme.cyan)
                                    MetricCard(label: t("This week", "本周"), value: compact(snapshot.thisWeek.totalTokens), icon: "calendar.badge.clock", tint: theme.violet)
                                    MetricCard(label: t("This month", "本月"), value: compact(snapshot.thisMonth.totalTokens), icon: "calendar", tint: theme.lime)
                                }
                                if model.settings.showTrend {
                                    trendCard(model.settings.showAdvanced && trendPeriod == 90 ? (snapshot.historyDailyUsage ?? []) :
                                              (trendPeriod == 30 ? snapshot.monthDailyUsage : snapshot.dailyUsage))
                                }
                            }
                        } else {
                            GlassCard { Text(model.error ?? t("Reading local Codex status…", "正在读取本机 Codex 状态…")).foregroundStyle(theme.muted) }
                        }
                        footer
                    }
                    .frame(width: max(0, geometry.size.width - horizontalInset * 2), alignment: .leading)
                    .padding(.horizontal, horizontalInset)
                    .padding(.vertical, 20)
                }
                .scrollIndicators(.hidden)
            }
        }
        .frame(width: 430, height: 690)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(theme.border, lineWidth: 1))
        .environment(\.pulsePalette, theme)
        .preferredColorScheme(model.settings.theme == "system" ? nil : (model.settings.theme == "dark" ? .dark : .light))
        .onChange(of: model.settings.showAdvanced) { enabled in
            if !enabled && trendPeriod == 90 { trendPeriod = 7 }
        }
    }

    private var header: some View {
        HStack {
            HStack(spacing: 8) {
                Image(nsImage: model.statusIcon ?? NSImage(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("codex-mark.png")) ?? NSImage())
                    .resizable().frame(width: 26, height: 26)
                Text("Codex Dashboard").font(.system(size: 12, weight: .heavy, design: .rounded))
                    .tracking(2.0).foregroundStyle(theme.text)
            }
            Spacer()
            Button(action: openSettings) {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 13)).foregroundStyle(theme.muted)
            }
            .buttonStyle(.plain)
            .help(t("Settings", "设置"))
        }
    }

    private func sectionHeader(_ title: String, detail: String, icon: String, tint: Color) -> some View {
        HStack(spacing: 7) {
            Image(systemName: icon).foregroundStyle(tint)
            Text(title).font(.system(size: 12, weight: .bold)).foregroundStyle(theme.text)
            Spacer()
            Text(detail)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(tint)
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background(tint.opacity(0.12), in: Capsule())
        }
        .padding(.horizontal, 2)
        .padding(.top, 4)
    }

    private func updateCard(_ update: UpdateInfo) -> some View {
        GlassCard {
            HStack(spacing: 10) {
                Image(systemName: "arrow.down.circle.fill")
                    .font(.system(size: 20)).foregroundStyle(theme.lime)
                VStack(alignment: .leading, spacing: 3) {
                    Text(t("Update available \(update.latestVersion)", "发现新版本 \(update.latestVersion)"))
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
                    Text(t("Install on click, then restart", "点击后更新，完成时会重新启动"))
                        .font(.system(size: 10)).foregroundStyle(theme.muted)
                }
                Spacer()
                Button(action: installUpdate) {
                    Text(t("Update & restart", "更新并重启")).font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(theme.cyan)
                        .padding(.horizontal, 10).padding(.vertical, 7)
                        .background(theme.cyan.opacity(0.13), in: Capsule())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var accountOverview: some View {
        let account = model.snapshot?.account
        let windows = quotaWindows(account, language: model.settings.language)
        let resetCredits = account?.stale == true ? nil : account?.rateLimitResetCredits
        let creditInfo = account?.rateLimits?.credits ?? account?.rateLimitsByLimitId?.values.compactMap { $0.credits }.first
        let identity = account?.displayName ?? account?.email ?? (account?.authType == "apiKey" ? "API Key" : t("Loading account…", "Codex 账号信息加载中"))
        let subtitle = account?.displayName != nil ? (account?.email ?? t("ChatGPT sign-in", "ChatGPT 登录")) :
            (account?.authType == "chatgpt" ? t("ChatGPT sign-in", "ChatGPT 登录") :
            (account?.authType == "apiKey" ? t("Billed by API usage", "按 API 用量计费") :
             (account?.authType == "amazonBedrock" ? "Amazon Bedrock" : t("Codex account", "Codex 账号"))))
        let badge = account?.authType == "apiKey" ? "API" : (account?.planType ?? "—").uppercased()
        return GlassCard {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(theme.violet.opacity(0.22)).frame(width: 40, height: 40)
                    Text(String(identity.prefix(1)).uppercased())
                        .font(.system(size: 17, weight: .bold)).foregroundStyle(theme.violet)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(identity)
                        .font(.system(size: 12, weight: .medium)).foregroundStyle(theme.text)
                        .lineLimit(1).truncationMode(.middle)
                    Text(subtitle)
                        .font(.system(size: 10)).foregroundStyle(theme.muted)
                }
                Spacer()
                Text(badge)
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(theme.cyan)
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(theme.cyan.opacity(0.12), in: Capsule())
            }
            Rectangle().fill(theme.border).frame(height: 1).padding(.vertical, 6)
            if account?.authType == "apiKey" {
                Label(t("Billed by OpenAI API usage", "按 OpenAI API 用量计费"), systemImage: "key.fill")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
                Text(t("ChatGPT plan quotas do not apply. Local token stats remain available.", "ChatGPT 套餐额度不适用于此账号，本机 Token 统计仍可使用。"))
                    .font(.system(size: 10)).foregroundStyle(theme.muted)
                Link(t("View API usage", "查看 API 用量"), destination: URL(string: "https://platform.openai.com/usage")!)
                    .font(.system(size: 10)).foregroundStyle(theme.cyan)
            } else if account?.authType == "amazonBedrock" {
                Text(t("This sign-in method has no ChatGPT plan quota", "当前登录方式不提供 ChatGPT 套餐额度"))
                    .font(.system(size: 11)).foregroundStyle(theme.muted)
            } else {
                HStack {
                    Label(t("Plan quota", "套餐额度"), systemImage: "gauge.with.dots.needle.67percent")
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
                    Spacer()
                    if let count = resetCredits?.availableCount {
                        Button { showResetDetails.toggle() } label: {
                            HStack(spacing: 5) {
                                Image(systemName: "arrow.counterclockwise")
                                Text(t("Reset cards \(count)", "重置卡 \(count)"))
                                Image(systemName: showResetDetails ? "chevron.up" : "chevron.down")
                                    .font(.system(size: 8, weight: .bold))
                            }
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(theme.lime)
                            .padding(.horizontal, 9).padding(.vertical, 5)
                            .background(theme.lime.opacity(0.12), in: Capsule())
                        }
                        .buttonStyle(.plain)
                        .help(t("View reset card expiration", "查看重置卡有效期"))
                    }
                }
                if windows.isEmpty {
                    Text(t("No quota windows returned yet", "当前账号未返回额度窗口，等待刷新"))
                        .font(.system(size: 10)).foregroundStyle(theme.muted)
                } else {
                    ForEach(windows) { window in quotaRow(window) }
                }
                if showResetDetails, let resetCredits {
                    resetDetails(resetCredits)
                }
                if let creditInfo, creditInfo.hasCredits == true {
                    Text(t("Workspace credits · \(creditInfo.unlimited == true ? "Unlimited" : (creditInfo.balance ?? "Pending"))",
                           "工作区积分 · \(creditInfo.unlimited == true ? "无限制" : (creditInfo.balance ?? "待更新"))"))
                        .font(.system(size: 10)).foregroundStyle(theme.muted)
                }
            }
        }
    }

    private var hero: some View {
        let visual = modelVisual(current?.model, language: model.settings.language)
        return GlassCard {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 9) {
                        Image(systemName: visual.symbol).foregroundStyle(visual.color)
                            .font(.system(size: 24))
                            .accessibilityLabel(visual.label)
                        Text(current?.model?.uppercased() ?? t("Waiting for chat", "等待会话"))
                            .font(.system(size: 25, weight: .bold, design: .rounded)).foregroundStyle(theme.text)
                            .lineLimit(1).minimumScaleFactor(0.7)
                    }
                    Text(t("Reasoning: \(effortLabel(current?.effort))  ·  \((current?.provider ?? "—").uppercased())",
                           "思考：\(effortLabel(current?.effort))  ·  \((current?.provider ?? "—").uppercased())"))
                        .font(.system(size: 11, weight: .medium)).foregroundStyle(theme.muted)
                }
                Spacer()
                Text(statusLabel)
                    .font(.system(size: 10, weight: .semibold))
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background((isRunning ? theme.lime : theme.muted).opacity(0.15), in: Capsule())
                    .foregroundStyle(isRunning ? theme.lime : theme.muted)
            }
            if let title = current?.title {
                Text(title).font(.system(size: 12, weight: .medium)).foregroundStyle(theme.text.opacity(0.85))
                    .lineLimit(2)
            }
            Divider().overlay(theme.border).padding(.vertical, 8)
            HStack(spacing: 7) {
                Image(systemName: "folder.fill").foregroundStyle(theme.violet)
                Text(current?.cwd ?? t("No working directory", "暂无工作目录")).lineLimit(1).truncationMode(.middle)
            }
            .font(.system(size: 11, design: .monospaced)).foregroundStyle(theme.muted)
            HStack {
                Text(t("This chat · \(compact(current?.usage.totalTokens ?? 0)) tokens", "本会话累计 \(compact(current?.usage.totalTokens ?? 0)) tokens"))
                Spacer()
                Text(t("Updated \(clock(current?.updatedAt))", "更新于 \(clock(current?.updatedAt))"))
            }
            .font(.system(size: 10, design: .monospaced)).foregroundStyle(theme.muted.opacity(0.75))
            .padding(.top, 8)
            HStack {
                Text(current?.originator ?? "Codex")
                Spacer()
                if let started = current?.turnStartedAt, isRunning {
                    Text(t("Running for \(duration(Int((parseDate(model.snapshot?.updatedAt)?.timeIntervalSince1970 ?? Double(started)) * 1000) - started * 1000, language: model.settings.language))",
                           "本轮已运行 \(duration(Int((parseDate(model.snapshot?.updatedAt)?.timeIntervalSince1970 ?? Double(started)) * 1000) - started * 1000, language: model.settings.language))"))
                } else if let elapsed = current?.lastDurationMs {
                    Text(t("Last turn \(duration(elapsed, language: model.settings.language))",
                           "上一轮 \(duration(elapsed, language: model.settings.language))"))
                }
            }
            .font(.system(size: 10)).foregroundStyle(theme.muted.opacity(0.75))
        }
    }

    private func effortLabel(_ effort: String?) -> String {
        switch effort {
        case "none": return t("Off", "关闭")
        case "minimal": return t("Minimal", "极低")
        case "low": return t("Low", "低")
        case "medium": return t("Medium", "中")
        case "high": return t("High", "高")
        case "xhigh": return t("Extra high", "超高")
        case "max": return t("Max", "最大")
        case "ultra": return t("Ultra", "极致")
        default: return t("Unknown", "未知")
        }
    }

    private var contextCard: some View {
        let input = current?.lastInputTokens ?? 0
        let window = current?.contextWindow ?? 0
        let remaining = window > 0 ? max(0, 1 - Double(input) / Double(window)) : 0
        return GlassCard {
            HStack {
                Label(t("Chat context remaining", "本会话上下文剩余"), systemImage: "circle.hexagongrid.fill")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
                Spacer()
                Text(window > 0 ? t("≈ \(Int(remaining * 100))%", "约 \(Int(remaining * 100))%") : t("No data", "暂无数据"))
                    .font(.system(size: 18, weight: .bold, design: .rounded)).foregroundStyle(theme.cyan)
            }
            MeterBar(fraction: remaining, tint: theme.cyan).padding(.vertical, 8)
            HStack {
                Text(t("Latest input \(compact(input))", "最近请求输入 \(compact(input))"))
                Spacer()
                Text(t("Window \(compact(window))", "窗口 \(compact(window))"))
            }
            .font(.system(size: 10, design: .monospaced)).foregroundStyle(theme.muted)
            Text(t("Estimated from latest input, not Codex's exact context count",
                   "按最近请求输入估算，非 Codex 精确上下文计数"))
                .font(.system(size: 10)).foregroundStyle(theme.muted.opacity(0.7)).padding(.top, 3)
        }
    }

    private func quotaRow(_ window: QuotaWindow) -> some View {
        let tint = window.durationMinutes == 10_080 ? theme.violet : theme.cyan
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(window.title)
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(theme.muted)
                Spacer()
                Text(window.remaining.map { String(format: t("%.0f%% left", "剩余 %.0f%%"), $0) } ?? t("Remaining unavailable", "余量未提供"))
                    .font(.system(size: 16, weight: .bold, design: .rounded)).foregroundStyle(tint)
            }
            MeterBar(fraction: (window.remaining ?? 0) / 100, tint: tint)
            Text(t("Resets \(resetTime(window.resetsAt, language: model.settings.language))",
                   "重置 \(resetTime(window.resetsAt, language: model.settings.language))"))
                .font(.system(size: 10, design: .monospaced)).foregroundStyle(theme.muted)
        }
        .padding(.top, 2)
    }

    private func resetDetails(_ credits: ResetCredits) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Rectangle().fill(theme.border).frame(height: 1).padding(.vertical, 3)
            let details = (credits.credits ?? []).filter { $0.status == "available" }
            if details.isEmpty {
                Text(credits.availableCount == 0 ? t("No reset cards available", "当前没有可用重置卡") : t("Only the count was provided", "服务只返回数量，未返回详情"))
                    .font(.system(size: 10)).foregroundStyle(theme.muted)
            } else {
                ForEach(details.indices, id: \.self) { index in
                    HStack {
                        Text(details[index].title == "Full reset" ? t("Full reset", "完整额度重置") : (details[index].title ?? t("Reset card \(index + 1)", "重置卡 \(index + 1)")))
                        Spacer()
                        Text(details[index].expiresAt.map { t("Expires \(resetTime($0, language: model.settings.language))", "有效期 \(resetTime($0, language: model.settings.language))") } ?? t("Expiry unavailable", "有效期未提供"))
                    }
                    .font(.system(size: 10)).foregroundStyle(theme.muted)
                }
            }
            Text(t("Display only · cards are never used automatically", "只读展示，不会自动消耗重置卡"))
                .font(.system(size: 10)).foregroundStyle(theme.muted.opacity(0.7))
        }
    }

    private var breakdownCard: some View {
        let usage = current?.usage
        let input = usage?.inputTokens ?? 0
        let output = usage?.outputTokens ?? 0
        let cached = usage?.cachedInputTokens ?? 0
        return GlassCard {
            Text(t("Chat token breakdown", "本会话 Token 构成")).font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
            HStack {
                breakdown(t("Input", "输入"), compact(input), theme.cyan)
                breakdown(t("Cached input", "缓存输入"), compact(cached), theme.violet)
                breakdown(t("Output", "输出"), compact(output), theme.lime)
            }
            .padding(.top, 7)
            Text(t("Input includes cached input; output includes \(compact(usage?.reasoningOutputTokens ?? 0)) reasoning tokens",
                   "输入含缓存输入；输出含推理输出 \(compact(usage?.reasoningOutputTokens ?? 0))"))
                .font(.system(size: 10, design: .monospaced)).foregroundStyle(theme.muted)
                .padding(.top, 8)
        }
    }

    private func breakdown(_ title: String, _ value: String, _ tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) { Circle().fill(tint).frame(width: 5, height: 5); Text(title) }
                .font(.system(size: 10)).foregroundStyle(theme.muted)
            Text(value).font(.system(size: 17, weight: .semibold, design: .rounded)).foregroundStyle(theme.text)
                .lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func trendCard(_ points: [DailyPoint]) -> some View {
        let maximum = max(points.map(\.totalTokens).max() ?? 1, 1)
        return GlassCard {
            HStack {
                Text(t("Local token trend", "本机 Token 趋势")).font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
                Spacer()
                Button(t("7 days", "7 天")) { trendPeriod = 7; hoveredDay = nil }
                    .foregroundStyle(trendPeriod == 7 ? theme.cyan : theme.muted)
                Button(t("Month", "本月")) { trendPeriod = 30; hoveredDay = nil }
                    .foregroundStyle(trendPeriod == 30 ? theme.cyan : theme.muted)
                if model.settings.showAdvanced {
                    Button(t("90 days", "90 天")) { trendPeriod = 90; hoveredDay = nil }
                        .foregroundStyle(trendPeriod == 90 ? theme.cyan : theme.muted)
                }
            }
            .buttonStyle(.plain)
            HStack {
                if let point = hoveredDay {
                    Text(point.date).foregroundStyle(theme.muted)
                    Spacer()
                    Text("\(point.totalTokens.formatted()) tokens")
                        .fontWeight(.semibold).foregroundStyle(theme.cyan)
                } else {
                    Text(t("Hover a bar for daily usage", "悬停柱形查看每日用量")).foregroundStyle(theme.muted)
                    Spacer()
                }
            }
            .font(.system(size: 10, design: .monospaced))
            .frame(height: 16)
            HStack(alignment: .bottom, spacing: points.count > 7 ? 2 : 9) {
                ForEach(points) { point in
                    Button {
                        hoveredDay = point
                    } label: {
                        VStack(spacing: 6) {
                            Spacer(minLength: 0)
                            RoundedRectangle(cornerRadius: 5)
                                .fill(LinearGradient(colors: [theme.cyan, theme.violet], startPoint: .top, endPoint: .bottom))
                                .opacity(hoveredDay == nil || hoveredDay?.id == point.id ? 1 : 0.5)
                                .shadow(color: hoveredDay?.id == point.id ? theme.cyan.opacity(0.65) : .clear, radius: 5)
                                .frame(height: max(5, 64 * CGFloat(point.totalTokens) / CGFloat(maximum)))
                            if points.count <= 7 {
                                Text(String(point.date.suffix(2)))
                                    .font(.system(size: 9, design: .monospaced)).foregroundStyle(theme.muted)
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .frame(maxWidth: .infinity)
                    .onHover { inside in
                        if inside { hoveredDay = point }
                    }
                    .accessibilityLabel("\(point.date) · \(point.totalTokens.formatted()) tokens")
                    .help("\(point.date) · \(point.totalTokens.formatted()) tokens")
                }
            }
            .frame(height: points.count > 7 ? 70 : 88)
            .padding(.top, 4)
            if points.count > 7 {
                HStack {
                    Text(points.first?.date ?? "")
                    Spacer()
                    Text(points.last?.date ?? "")
                }
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(theme.muted)
            }
        }
    }

    private func sessionsCard(_ sessions: [Session]) -> some View {
        GlassCard {
            Text(t("Recent chats", "最近会话")).font(.system(size: 12, weight: .semibold)).foregroundStyle(theme.text)
            ForEach(sessions.prefix(4)) { session in
                HStack(spacing: 8) {
                    Circle().fill(session.taskStatus == "running" ? theme.lime : theme.muted.opacity(0.6))
                        .frame(width: 6, height: 6)
                    Text(session.model ?? t("Unknown model", "未知模型")).foregroundStyle(theme.text)
                    Spacer()
                    Text(compact(session.usage.totalTokens)).foregroundStyle(theme.cyan)
                    Text(clock(session.updatedAt)).foregroundStyle(theme.muted)
                }
                .font(.system(size: 10, design: .monospaced))
                .padding(.top, 6)
            }
        }
    }

    private var footer: some View {
        HStack {
            Text(model.updateMessage ?? (model.error == nil ?
                 (model.snapshot?.selectionMode == "desktop_view" ? t("Follows Codex window · refreshes every ~2s", "跟随 Codex 窗口 · 约每 2 秒刷新") :
                  t("Shows recent activity · refreshes every ~2s", "按最近活动显示 · 约每 2 秒刷新")) :
                  t("Read error: \(model.error ?? "")", "读取异常：\(model.error ?? "")")))
                .lineLimit(1).foregroundStyle(theme.muted)
            Spacer()
            Button(action: checkUpdate) { Image(systemName: "arrow.down.circle") }
                .buttonStyle(.plain).help(t("Check for updates", "检查更新"))
            Button(action: refresh) { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.plain).help(t("Refresh now", "立即刷新"))
            Button(action: quit) { Image(systemName: "power") }
                .buttonStyle(.plain).help(t("Quit", "退出"))
        }
        .font(.system(size: 10)).foregroundStyle(theme.muted)
        .padding(.horizontal, 3)
    }
}

private struct SettingsView: View {
    @Environment(\.colorScheme) private var systemColorScheme
    @ObservedObject var model: DashboardModel
    let exportHistory: () -> Void
    let settingsChanged: () -> Void

    private var theme: PulsePalette {
        let light = model.settings.theme == "light" ||
            (model.settings.theme == "system" && systemColorScheme == .light)
        return PulsePalette(light: light, accent: model.settings.showAdvanced ? model.settings.accent : "cyan")
    }

    private func t(_ en: String, _ zh: String) -> String { model.settings.language == "zh" ? zh : en }
    private func bind<Value>(_ key: WritableKeyPath<AppSettings, Value>) -> Binding<Value> {
        Binding(get: { model.settings[keyPath: key] }, set: { value in
            var next = model.settings
            next[keyPath: key] = value
            model.settings = next
        })
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text(t("Settings", "设置"))
                    .font(.system(size: 21, weight: .bold)).foregroundStyle(theme.text)
                GlassCard {
                    Text(t("Appearance", "外观")).font(.system(size: 13, weight: .bold)).foregroundStyle(theme.text)
                    Picker(t("Language", "语言"), selection: bind(\.language)) {
                        Text("English").tag("en")
                        Text("中文").tag("zh")
                    }
                    Picker(t("Theme", "主题"), selection: bind(\.theme)) {
                        Text(t("System", "跟随系统")).tag("system")
                        Text(t("Dark", "深色")).tag("dark")
                        Text(t("Light", "浅色")).tag("light")
                    }
                }
                GlassCard {
                    Text(t("Visible information", "显示内容")).font(.system(size: 13, weight: .bold)).foregroundStyle(theme.text)
                    Toggle(t("Chat context estimate", "会话上下文估算"), isOn: bind(\.showContext))
                    Toggle(t("Chat token breakdown", "会话 Token 构成"), isOn: bind(\.showBreakdown))
                    Toggle(t("Local usage totals", "本机用量汇总"), isOn: bind(\.showLocalUsage))
                    Toggle(t("Local usage trend", "本机用量趋势"), isOn: bind(\.showTrend))
                        .disabled(!model.settings.showLocalUsage)
                }
                GlassCard {
                    Text(t("Personal information", "个人信息")).font(.system(size: 13, weight: .bold)).foregroundStyle(theme.text)
                    infoRow(t("Codex account", "Codex 账号"), model.snapshot?.account?.displayName ?? "—")
                    infoRow(t("Email", "邮箱"), model.snapshot?.account?.email ?? "—")
                    infoRow(t("Plan", "套餐"), (model.snapshot?.account?.planType ?? "—").uppercased())
                    infoRow(t("Sign-in", "登录方式"), model.snapshot?.account?.authType == "chatgpt" ? "ChatGPT" :
                            (model.snapshot?.account?.authType == "apiKey" ? "API Key" : (model.snapshot?.account?.authType ?? "—")))
                }
                GlassCard {
                    Text(t("Advanced tools", "高级工具")).font(.system(size: 13, weight: .bold)).foregroundStyle(theme.text)
                    Toggle(t("Enable advanced tools", "启用高级工具"), isOn: bind(\.showAdvanced))
                    Text(t("Includes 90-day history, CSV export, accent colors and execution change signals.",
                           "包含 90 天历史、CSV 导出、强调色和运行变化线索。"))
                        .font(.system(size: 10)).foregroundStyle(theme.muted)
                    if let message = model.settingsMessage {
                        Text(message).font(.system(size: 10)).foregroundStyle(theme.muted)
                    }
                    Picker(t("Accent color", "强调色"), selection: bind(\.accent)) {
                        Text(t("Cyan", "青色")).tag("cyan")
                        Text(t("Violet", "紫色")).tag("violet")
                        Text(t("Green", "绿色")).tag("green")
                    }
                    .disabled(!model.settings.showAdvanced)
                    Button(t("Export 90-day CSV", "导出 90 天 CSV"), action: exportHistory)
                        .disabled(!model.settings.showAdvanced)
                }
                GlassCard {
                    Text(t("Support the project", "支持项目"))
                        .font(.system(size: 13, weight: .bold)).foregroundStyle(theme.text)
                    Text(t("If Codex Dashboard helps you, you can star the repository on GitHub. This is optional.",
                           "如果 Codex Dashboard 对你有帮助，可以自愿在 GitHub 为仓库加 Star。"))
                        .font(.system(size: 10)).foregroundStyle(theme.muted)
                    Link(t("Open repository on GitHub", "在 GitHub 打开仓库"),
                         destination: URL(string: "https://github.com/xushanpei/codex-dashboard")!)
                        .font(.system(size: 11))
                }
                if model.settings.showAdvanced {
                    GlassCard {
                        Text(t("Execution change signals", "运行变化线索"))
                            .font(.system(size: 13, weight: .bold)).foregroundStyle(theme.text)
                        let signals = model.snapshot?.runtimeSignals
                        if let change = signals?.modelChange {
                            infoRow(t("Model changed", "模型变化"), "\(change.from ?? "—") → \(change.to ?? "—")")
                            Text(t("Observed \(signalTime(change.at))", "观察于 \(signalTime(change.at))"))
                                .font(.system(size: 10)).foregroundStyle(theme.muted)
                        }
                        if let reduction = signals?.effortReduction {
                            infoRow(t("Reasoning effort lowered", "思考档位降低"), "\(reduction.from ?? "—") → \(reduction.to ?? "—")")
                            Text(t("Observed \(signalTime(reduction.at))", "观察于 \(signalTime(reduction.at))"))
                                .font(.system(size: 10)).foregroundStyle(theme.muted)
                        }
                        if signals?.modelChange == nil && signals?.effortReduction == nil {
                            Text(t("No model or reasoning-level changes observed in this chat.",
                                   "当前会话未观察到模型或思考档位变化。"))
                                .font(.system(size: 10)).foregroundStyle(theme.muted)
                        }
                        Text(t("These are log signals. A user setting change can produce them; they cannot prove answer quality declined.",
                               "这些是日志线索，手动切换设置也会产生；不能据此证明回答质量下降。"))
                            .font(.system(size: 10)).foregroundStyle(theme.muted)
                    }
                }
            }
            .padding(20)
        }
        .background(theme.bg)
        .environment(\.pulsePalette, theme)
        .preferredColorScheme(model.settings.theme == "system" ? nil : (model.settings.theme == "dark" ? .dark : .light))
        .onChange(of: model.settings.language) { _ in settingsChanged() }
    }

    private func infoRow(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title).foregroundStyle(theme.muted)
            Spacer()
            Text(value).foregroundStyle(theme.text).lineLimit(1).truncationMode(.middle)
        }
        .font(.system(size: 11))
    }

    private func signalTime(_ stamp: String?) -> String {
        guard let date = parseDate(stamp) else { return "—" }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: model.settings.language == "zh" ? "zh_CN" : "en_US")
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}

private final class PulsePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class CodexDashboardApp: NSObject, NSApplicationDelegate {
    private let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var panel: PulsePanel?
    private var globalClickMonitor: Any?
    private var localEventMonitor: Any?
    private let model = DashboardModel()
    private let logo = StatusIconRenderer()
    private var inFlight = false
    private var updateCheckInFlight = false
    private var previewWindow: NSWindow?
    private var settingsWindow: NSWindow?
    private var currentVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    }
    private func l(_ en: String, _ zh: String) -> String { model.settings.language == "zh" ? zh : en }
    private lazy var pythonExecutable: URL? = {
        let environment = ProcessInfo.processInfo.environment
        #if arch(arm64)
        let preferred = ["/opt/homebrew/bin/python3", "/usr/bin/python3", "/usr/local/bin/python3"]
        #else
        let preferred = ["/usr/local/bin/python3", "/usr/bin/python3", "/opt/homebrew/bin/python3"]
        #endif
        let fromPath = (environment["PATH"] ?? "").split(separator: ":").map { "\($0)/python3" }
        for path in ([environment["CODEX_DASHBOARD_PYTHON"]].compactMap { $0 } + preferred + fromPath) {
            if FileManager.default.isExecutableFile(atPath: path) { return URL(fileURLWithPath: path) }
        }
        return nil
    }()

    private func showMenuStatus(_ state: String, iconState: String, remaining: Int?) {
        let font = NSFont.systemFont(ofSize: 11, weight: .medium)
        let numberFont = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .semibold)
        let text = NSMutableAttributedString()
        if let remaining {
            text.append(NSAttributedString(string: l("Left ", "剩余 "), attributes: [
                .font: font, .foregroundColor: NSColor.labelColor
            ]))
            text.append(NSAttributedString(string: "\(remaining)%", attributes: [
                .font: numberFont, .foregroundColor: NSColor.labelColor
            ]))
        } else {
            let fallback = model.snapshot?.account?.authType == "apiKey" ? "API Key" : l("Quota unknown", "额度未知")
            text.append(NSAttributedString(string: fallback, attributes: [
                .font: font, .foregroundColor: NSColor.labelColor
            ]))
        }
        let icon = logo.image(for: iconState)
        status.button?.image = icon
        model.statusIcon = icon
        status.button?.attributedTitle = text
        status.button?.toolTip = remaining.map { l("Codex Dashboard · \(state) · \($0)% quota left", "Codex Dashboard · \(state) · 套餐额度剩余 \($0)%") } ?? "Codex Dashboard · \(state)"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        status.button?.imagePosition = .imageLeft
        showMenuStatus(l("Loading", "加载中"), iconState: "idle", remaining: nil)
        status.button?.target = self
        status.button?.action = #selector(handleStatusClick)
        status.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])
        let panel = PulsePanel(contentRect: NSRect(x: 0, y: 0, width: 430, height: 690),
                               styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Codex Dashboard"
        panel.level = .popUpMenu
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.transient, .moveToActiveSpace, .fullScreenAuxiliary]
        panel.contentView = NSHostingView(rootView: DashboardView(
            model: model, refresh: { [weak self] in self?.refreshNow() },
            checkUpdate: { [weak self] in self?.checkForUpdates(manual: true) },
            installUpdate: { [weak self] in self?.installUpdate() },
            openSettings: { [weak self] in self?.showSettings() },
            quit: { NSApplication.shared.terminate(nil) }))
        self.panel = panel
        let isPreview = ProcessInfo.processInfo.environment["CODEX_DASHBOARD_PREVIEW"] == "1"
        if isPreview {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 430, height: 690),
                                  styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.title = "Codex Dashboard Preview"
            window.contentView = NSHostingView(rootView: DashboardView(
                model: model, refresh: { [weak self] in self?.refreshNow() },
                checkUpdate: { [weak self] in self?.checkForUpdates(manual: true) },
                installUpdate: { [weak self] in self?.installUpdate() },
                openSettings: { [weak self] in self?.showSettings() },
                quit: { NSApplication.shared.terminate(nil) }))
            window.center()
            window.makeKeyAndOrderFront(nil)
            NSApplication.shared.activate(ignoringOtherApps: true)
            previewWindow = window
        }
        refreshNow()
        readUpdateStatus()
        if isPreview && ProcessInfo.processInfo.environment["CODEX_DASHBOARD_PREVIEW_UPDATE"] == "1" {
            model.updateInfo = UpdateInfo(available: true, latestVersion: "0.1.5",
                                          releaseUrl: "https://github.com/xushanpei/codex-dashboard/releases")
        } else {
            checkForUpdates()
        }
        if ProcessInfo.processInfo.environment["CODEX_DASHBOARD_SHOW_PANEL"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.showPanel() }
        }
        if !isPreview {
            let timer = Timer(timeInterval: 2, target: self, selector: #selector(refreshNow), userInfo: nil, repeats: true)
            RunLoop.main.add(timer, forMode: .common)
            let updateTimer = Timer(timeInterval: 6 * 60 * 60, target: self,
                                    selector: #selector(checkUpdatesTimer), userInfo: nil, repeats: true)
            RunLoop.main.add(updateTimer, forMode: .common)
        }
    }

    private func readUpdateStatus() {
        let path = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".codex/codex-dashboard/update-status.json")
        if let data = try? Data(contentsOf: path),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: String],
           let message = value["message"] {
            model.updateMessage = message
            try? FileManager.default.removeItem(at: path)
        }
    }

    private func showSettings() {
        hidePanel()
        if settingsWindow == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 620),
                                  styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            window.title = l("Codex Dashboard Settings", "Codex Dashboard 设置")
            window.minSize = NSSize(width: 420, height: 480)
            window.isReleasedWhenClosed = false
            window.contentView = NSHostingView(rootView: SettingsView(
                model: model,
                exportHistory: { [weak self] in self?.exportHistory() },
                settingsChanged: { [weak self] in self?.refreshSettingsTitle() }))
            window.center()
            settingsWindow = window
        }
        refreshSettingsTitle()
        settingsWindow?.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    private func refreshSettingsTitle() {
        settingsWindow?.title = l("Codex Dashboard Settings", "Codex Dashboard 设置")
        refreshNow()
    }

    private func exportHistory() {
        guard model.settings.showAdvanced, let points = model.snapshot?.historyDailyUsage else { return }
        let panel = NSSavePanel()
        panel.title = model.settings.language == "zh" ? "导出 90 天用量" : "Export 90-day usage"
        panel.nameFieldStringValue = "codex-dashboard-90-days.csv"
        panel.canCreateDirectories = true
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            let rows = points.map { "\($0.date),\($0.totalTokens)" }.joined(separator: "\n")
            let csv = "date,total_tokens\n" + rows + "\n"
            do {
                try csv.write(to: url, atomically: true, encoding: .utf8)
                self?.model.settingsMessage = self?.model.settings.language == "zh" ? "CSV 已导出" : "CSV exported."
            } catch {
                self?.model.settingsMessage = self?.model.settings.language == "zh" ? "导出失败" : "Export failed."
            }
        }
    }

    @objc private func checkUpdatesTimer() { checkForUpdates() }

    private func checkForUpdates(manual: Bool = false) {
        guard !updateCheckInFlight else { return }
        guard let pythonExecutable else {
            if manual { model.updateMessage = l("Python 3 not found; cannot check for updates", "未找到 Python 3，无法检查更新") }
            return
        }
        updateCheckInFlight = true
        if manual { model.updateMessage = l("Checking for updates…", "正在检查更新…") }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let script = Bundle.main.resourceURL!.appendingPathComponent("updater.py")
            let process = Process()
            process.executableURL = pythonExecutable
            process.arguments = [script.path, "--check", "--current-version", self?.currentVersion ?? "0.0.0"]
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = Pipe()
            var update: UpdateInfo?
            var readError: String?
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                if process.terminationStatus != 0 { throw NSError(domain: "CodexDashboardUpdate", code: Int(process.terminationStatus)) }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                update = try decoder.decode(UpdateInfo.self, from: data)
            } catch { readError = error.localizedDescription }
            DispatchQueue.main.async {
                self?.model.updateInfo = update?.available == true ? update : nil
                if manual {
                    self?.model.updateMessage = readError == nil ?
                        (update?.available == true ? self?.l("Update available \(update?.latestVersion ?? "")", "发现新版本 \(update?.latestVersion ?? "")") :
                         self?.l("Up to date", "已是最新版本")) :
                        self?.l("Update check failed; try again later", "检查更新失败，请稍后重试")
                }
                self?.updateCheckInFlight = false
            }
        }
    }

    private func installUpdate() {
        guard model.updateInfo?.available == true, let pythonExecutable else { return }
        let script = Bundle.main.resourceURL!.appendingPathComponent("updater.py")
        let process = Process()
        process.executableURL = pythonExecutable
        process.arguments = [script.path, "--install-macos", "--current-version", currentVersion,
                             "--app-path", Bundle.main.bundlePath, "--wait-pid",
                             String(ProcessInfo.processInfo.processIdentifier)]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            model.updateMessage = l("Updating; the app will restart…", "正在更新，完成后会重新启动…")
            try process.run()
            NSApplication.shared.terminate(nil)
        } catch {
            model.updateMessage = l("Could not start updater: \(error.localizedDescription)", "无法启动更新程序：\(error.localizedDescription)")
        }
    }

    @objc private func handleStatusClick() {
        if NSApp.currentEvent?.type == .rightMouseUp {
            hidePanel()
            showContextMenu()
        } else {
            togglePanel()
        }
    }

    private func showContextMenu() {
        let menu = NSMenu(title: "Codex Dashboard")
        menu.autoenablesItems = false
        let session = model.snapshot?.currentSession
        let state = session?.taskStatus == "running" ? l("Running", "运行中") :
            (session?.taskStatus == "unconfirmed" ? l("Unconfirmed", "待确认") : l("Idle", "空闲"))
        let header = NSMenuItem(title: "Codex Dashboard  ·  \(state)", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        let account = model.snapshot?.account
        if account?.authType == "apiKey" {
            let item = NSMenuItem(title: l("API Key · billed by API usage", "API Key · 按 API 用量计费"), action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        } else {
            for window in quotaWindows(account, language: model.settings.language) {
                let amount = window.remaining.map { String(format: "%.0f%%", $0) } ?? l("unknown", "未知")
                let item = NSMenuItem(title: l("\(window.title)  \(amount) left  ·  resets \(resetTime(window.resetsAt, language: model.settings.language))",
                                                   "\(window.title)  剩余 \(amount)  ·  重置 \(resetTime(window.resetsAt, language: model.settings.language))"),
                                      action: nil, keyEquivalent: "")
                item.isEnabled = false
                menu.addItem(item)
            }
            if let count = account?.rateLimitResetCredits?.availableCount {
                let item = NSMenuItem(title: l("Reset cards  \(count) available", "额度重置卡  可用 \(count) 张"), action: nil, keyEquivalent: "")
                item.isEnabled = false
                menu.addItem(item)
            }
        }
        menu.addItem(.separator())
        addMenuAction(l("Open dashboard", "打开面板"), selector: #selector(openPanelFromMenu), to: menu)
        addMenuAction(l("Refresh now", "立即刷新"), selector: #selector(refreshNow), to: menu)
        addMenuAction(l("Check for updates", "检查更新"), selector: #selector(checkUpdatesFromMenu), to: menu)
        addMenuAction(l("Copy usage summary", "复制用量摘要"), selector: #selector(copyUsageSummary), to: menu)
        menu.addItem(.separator())
        let language = NSMenuItem(title: "Language / 语言", action: nil, keyEquivalent: "")
        let languageMenu = NSMenu(title: "Language")
        addMenuAction("English", selector: #selector(useEnglish), to: languageMenu).state = model.settings.language == "en" ? .on : .off
        addMenuAction("中文", selector: #selector(useChinese), to: languageMenu).state = model.settings.language == "zh" ? .on : .off
        language.submenu = languageMenu
        menu.addItem(language)
        let appearance = NSMenuItem(title: l("Theme", "主题"), action: nil, keyEquivalent: "")
        let appearanceMenu = NSMenu(title: "Theme")
        addMenuAction(l("Follow system", "跟随系统"), selector: #selector(useSystemTheme), to: appearanceMenu).state = model.settings.theme == "system" ? .on : .off
        addMenuAction(l("Dark", "深色"), selector: #selector(useDarkTheme), to: appearanceMenu).state = model.settings.theme == "dark" ? .on : .off
        addMenuAction(l("Light", "浅色"), selector: #selector(useLightTheme), to: appearanceMenu).state = model.settings.theme == "light" ? .on : .off
        appearance.submenu = appearanceMenu
        menu.addItem(appearance)
        addMenuAction(l("Settings…", "设置…"), selector: #selector(openSettingsFromMenu), to: menu)
        menu.addItem(.separator())
        addMenuAction(l("Open GitHub project", "打开 GitHub 项目"), selector: #selector(openGitHub), to: menu)
        addMenuAction(l("Quit Codex Dashboard", "退出 Codex Dashboard"), selector: #selector(quitFromMenu), to: menu)
        status.popUpMenu(menu)
    }

    @discardableResult private func addMenuAction(_ title: String, selector: Selector, to menu: NSMenu) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: "")
        item.target = self
        menu.addItem(item)
        return item
    }

    @objc private func openPanelFromMenu() { showPanel() }
    @objc private func openSettingsFromMenu() { showSettings() }
    @objc private func useEnglish() { model.settings.language = "en"; refreshNow() }
    @objc private func useChinese() { model.settings.language = "zh"; refreshNow() }
    @objc private func useSystemTheme() { model.settings.theme = "system" }
    @objc private func useDarkTheme() { model.settings.theme = "dark" }
    @objc private func useLightTheme() { model.settings.theme = "light" }
    @objc private func checkUpdatesFromMenu() { checkForUpdates(manual: true) }
    @objc private func openGitHub() {
        if let url = URL(string: "https://github.com/xushanpei/codex-dashboard") { NSWorkspace.shared.open(url) }
    }
    @objc private func quitFromMenu() { NSApplication.shared.terminate(nil) }

    @objc private func copyUsageSummary() {
        let snapshot = model.snapshot
        var lines = ["Codex Dashboard", l("Status: \(snapshot?.currentSession?.taskStatus == "running" ? "Running" : "Idle")",
                                            "当前状态：\(snapshot?.currentSession?.taskStatus == "running" ? "运行中" : "空闲")")]
        if let modelName = snapshot?.currentSession?.model { lines.append(l("Model: \(modelName)", "模型：\(modelName)")) }
        if let total = snapshot?.currentSession?.usage.totalTokens { lines.append(l("Chat total: \(total) tokens", "会话累计：\(total) tokens")) }
        if snapshot?.account?.authType == "apiKey" {
            lines.append(l("API Key: billed by API usage", "API Key 接入：按 API 用量计费"))
        } else {
            for window in quotaWindows(snapshot?.account, language: model.settings.language) {
                let amount = window.remaining.map { String(format: "%.0f%%", $0) } ?? l("unknown", "未知")
                lines.append(l("\(window.title): \(amount) left, resets \(resetTime(window.resetsAt, language: model.settings.language))",
                               "\(window.title)：剩余 \(amount)，重置 \(resetTime(window.resetsAt, language: model.settings.language))"))
            }
            if let count = snapshot?.account?.rateLimitResetCredits?.availableCount {
                lines.append(l("Reset cards: \(count) available", "额度重置卡：可用 \(count) 张"))
            }
        }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(lines.joined(separator: "\n"), forType: .string)
    }

    private func togglePanel() {
        if panel?.isVisible == true { hidePanel() }
        else { showPanel() }
    }

    private func showPanel() {
        guard let button = status.button, let window = button.window, let panel else { return }
        let anchor = window.convertToScreen(button.convert(button.bounds, to: nil))
        let visible = window.screen?.visibleFrame ?? NSScreen.main?.visibleFrame ?? anchor
        let margin: CGFloat = 8
        let width: CGFloat = 430, height: CGFloat = 690
        let x = min(max(anchor.midX - width / 2, visible.minX + margin), visible.maxX - width - margin)
        let y = max(visible.minY + margin, anchor.minY - height - margin)
        panel.setFrame(NSRect(x: x, y: y, width: width, height: height), display: true)
        panel.makeKeyAndOrderFront(nil)
        if ProcessInfo.processInfo.environment["CODEX_DASHBOARD_PREVIEW"] == "1" { return }
        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            DispatchQueue.main.async { self?.hidePanel() }
        }
        localEventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { [weak self] event in
            guard let self else { return event }
            if event.type == .keyDown && event.keyCode == 53 {
                self.hidePanel()
                return nil
            }
            if let clickedWindow = event.window,
               clickedWindow != self.panel && clickedWindow != self.status.button?.window {
                self.hidePanel()
            }
            return event
        }
    }

    private func hidePanel() {
        panel?.orderOut(nil)
        if let monitor = globalClickMonitor { NSEvent.removeMonitor(monitor); globalClickMonitor = nil }
        if let monitor = localEventMonitor { NSEvent.removeMonitor(monitor); localEventMonitor = nil }
    }

    @objc private func refreshNow() {
        readUpdateStatus()
        guard !inFlight else { return }
        guard let pythonExecutable else {
            model.error = l("Python 3 not found; install Python 3 or Xcode Command Line Tools", "未找到 Python 3，请安装 Python 3 或 Xcode 命令行工具")
            showMenuStatus(l("Read error", "读取异常"), iconState: "error", remaining: nil)
            return
        }
        inFlight = true
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let script = Bundle.main.resourceURL!.appendingPathComponent("collector.py")
            let process = Process()
            process.executableURL = pythonExecutable
            process.arguments = [script.path]
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = Pipe()
            var snapshot: Snapshot?
            var readError: String?
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                if process.terminationStatus != 0 { throw NSError(domain: "CodexDashboard", code: Int(process.terminationStatus)) }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                snapshot = try decoder.decode(Snapshot.self, from: data)
            } catch { readError = error.localizedDescription }
            DispatchQueue.main.async {
                if let snapshot {
                    self?.model.snapshot = snapshot
                    self?.model.error = nil
                    let session = snapshot.currentSession
                    let state = session?.taskStatus == "running" ? self?.l("Running", "运行中") ?? "Running" :
                        (session?.taskStatus == "unconfirmed" ? self?.l("Unconfirmed", "待确认") ?? "Unconfirmed" : self?.l("Idle", "空闲") ?? "Idle")
                    let iconState = session?.taskStatus == "running" ? "running" : (session?.taskStatus == "unconfirmed" ? "unconfirmed" : "idle")
                    let quota = quotaWindows(snapshot.account, language: self?.model.settings.language ?? "en").first
                    self?.showMenuStatus(state, iconState: iconState,
                                         remaining: quota?.remaining.map { Int($0) })
                    if snapshot.account?.authType == "apiKey" {
                        self?.status.button?.toolTip = self?.l("Codex Dashboard · \(state) · API Key", "Codex Dashboard · \(state) · API Key 接入")
                    } else if let quota {
                        self?.status.button?.toolTip = self?.l("Codex Dashboard · \(state) · \(quota.title): \(Int(quota.remaining ?? 0))% left",
                                                            "Codex Dashboard · \(state) · \(quota.title)剩余 \(Int(quota.remaining ?? 0))%")
                    }
                } else {
                    self?.model.error = readError ?? self?.l("Unknown error", "未知错误")
                    self?.showMenuStatus(self?.l("Status unknown", "状态未知") ?? "Status unknown", iconState: "error", remaining: nil)
                }
                self?.inFlight = false
            }
        }
    }
}

@main
struct CodexDashboardMain {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = CodexDashboardApp()
        app.delegate = delegate
        app.run()
    }
}
