import AppKit
import SwiftUI

private enum Theme {
    static let bg = Color(red: 0.035, green: 0.055, blue: 0.105)
    static let panel = Color(red: 0.075, green: 0.105, blue: 0.17)
    static let border = Color.white.opacity(0.11)
    static let muted = Color(red: 0.60, green: 0.68, blue: 0.80)
    static let cyan = Color(red: 0.29, green: 0.91, blue: 0.95)
    static let violet = Color(red: 0.69, green: 0.52, blue: 1.0)
    static let lime = Color(red: 0.63, green: 0.96, blue: 0.68)
}

private func modelVisual(_ model: String?) -> (symbol: String, color: Color, label: String) {
    let name = model?.lowercased() ?? ""
    if name.contains("astra") { return ("sparkles", Color(red: 0.83, green: 0.67, blue: 1), "群星") }
    if name.contains("sol") { return ("sun.max.fill", Color(red: 1, green: 0.77, blue: 0.36), "太阳") }
    if name.contains("terra") { return ("globe.europe.africa.fill", Color(red: 0.61, green: 0.91, blue: 0.57), "大地") }
    if name.contains("luna") { return ("moon.fill", Color(red: 0.68, green: 0.78, blue: 1), "月亮") }
    return ("cpu.fill", Theme.muted, "模型")
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

private struct Account: Decodable {
    let email: String?
    let planType: String?
    let authType: String?
    let rateLimits: AccountLimits?
    let stale: Bool?
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

private func resetTime(_ epoch: Int?) -> String {
    guard let epoch else { return "—" }
    return Date(timeIntervalSince1970: TimeInterval(epoch)).formatted(date: .abbreviated, time: .shortened)
}

private func duration(_ milliseconds: Int) -> String {
    let seconds = max(0, milliseconds / 1000)
    if seconds >= 3600 { return "\(seconds / 3600) 小时 \((seconds % 3600) / 60) 分" }
    if seconds >= 60 { return "\(seconds / 60) 分 \(seconds % 60) 秒" }
    return "\(seconds) 秒"
}

private struct GlassCard<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) { content }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.panel.opacity(0.88), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Theme.border, lineWidth: 1))
    }
}

private struct MeterBar: View {
    let fraction: Double
    let tint: Color
    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(.white.opacity(0.09))
                Capsule().fill(LinearGradient(colors: [tint, tint.opacity(0.55)], startPoint: .leading, endPoint: .trailing))
                    .frame(width: max(4, geometry.size.width * min(max(fraction, 0), 1)))
            }
        }
        .frame(height: 7)
    }
}

private struct MetricCard: View {
    let label: String
    let value: String
    let icon: String
    let tint: Color
    var body: some View {
        return GlassCard {
            HStack {
                Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.muted)
                Spacer()
                Image(systemName: icon).foregroundStyle(tint)
            }
            Text(value).font(.system(size: 25, weight: .semibold, design: .rounded))
                .foregroundStyle(.white).minimumScaleFactor(0.7).lineLimit(1)
            Text("TOKENS").font(.system(size: 9, weight: .bold, design: .monospaced))
                .tracking(1.5).foregroundStyle(tint)
        }
    }
}

private struct DashboardView: View {
    @ObservedObject var model: DashboardModel
    @State private var showMonthTrend = false
    @State private var hoveredDay: DailyPoint?
    private let horizontalInset: CGFloat = 20
    let refresh: () -> Void
    let checkUpdate: () -> Void
    let installUpdate: () -> Void
    let quit: () -> Void

    private var current: Session? { model.snapshot?.currentSession }
    private var primaryRate: RateLimit? {
        model.snapshot?.account?.stale == false ? model.snapshot?.account?.rateLimits?.primary : nil
    }
    private var isRunning: Bool { current?.taskStatus == "running" }
    private var statusLabel: String {
        guard current != nil else { return "暂无记录" }
        switch current?.taskStatus {
        case "running": return "运行中"
        case "unconfirmed": return "状态待确认"
        default: return "空闲"
        }
    }

    var body: some View {
        ZStack {
            Theme.bg
            Circle().fill(Theme.cyan.opacity(0.14)).frame(width: 290, height: 290).blur(radius: 90).offset(x: 150, y: -260)
            Circle().fill(Theme.violet.opacity(0.15)).frame(width: 220, height: 220).blur(radius: 80).offset(x: -170, y: 160)
            GeometryReader { geometry in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header
                        if let update = model.updateInfo, update.available { updateCard(update) }
                        accountCard
                        hero
                        if let snapshot = model.snapshot {
                            HStack {
                                Text("本机 Token 用量")
                                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                                Spacer()
                                Text("含本机所有登录账号")
                                    .font(.system(size: 10)).foregroundStyle(Theme.muted)
                            }
                            .padding(.horizontal, 2)
                            HStack(spacing: 10) {
                                MetricCard(label: "今日", value: compact(snapshot.today.totalTokens), icon: "sun.max.fill", tint: Theme.cyan)
                                MetricCard(label: "本周", value: compact(snapshot.thisWeek.totalTokens), icon: "calendar.badge.clock", tint: Theme.violet)
                                MetricCard(label: "本月", value: compact(snapshot.thisMonth.totalTokens), icon: "calendar", tint: Theme.lime)
                            }
                            contextCard
                            limitCard
                            breakdownCard
                            trendCard(showMonthTrend ? snapshot.monthDailyUsage : snapshot.dailyUsage)
                        } else {
                            GlassCard { Text(model.error ?? "正在读取本机 Codex 状态…").foregroundStyle(Theme.muted) }
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
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(Theme.border, lineWidth: 1))
    }

    private var header: some View {
        HStack {
            HStack(spacing: 8) {
                Image(nsImage: model.statusIcon ?? NSImage(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("codex-mark.png")) ?? NSImage())
                    .resizable().frame(width: 26, height: 26)
                Text("CODEX PULSE").font(.system(size: 12, weight: .heavy, design: .rounded))
                    .tracking(2.0).foregroundStyle(.white)
            }
            Spacer()
        }
    }

    private func updateCard(_ update: UpdateInfo) -> some View {
        GlassCard {
            HStack(spacing: 10) {
                Image(systemName: "arrow.down.circle.fill")
                    .font(.system(size: 20)).foregroundStyle(Theme.lime)
                VStack(alignment: .leading, spacing: 3) {
                    Text("发现新版本 \(update.latestVersion)")
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                    Text("点击后更新，完成时会重新启动")
                        .font(.system(size: 10)).foregroundStyle(Theme.muted)
                }
                Spacer()
                Button(action: installUpdate) {
                    Text("更新并重启").font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Theme.cyan)
                        .padding(.horizontal, 10).padding(.vertical, 7)
                        .background(Theme.cyan.opacity(0.13), in: Capsule())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var accountCard: some View {
        let account = model.snapshot?.account
        return GlassCard {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(Theme.violet.opacity(0.22)).frame(width: 40, height: 40)
                    Text(String(account?.email?.prefix(1) ?? "C").uppercased())
                        .font(.system(size: 17, weight: .bold)).foregroundStyle(Theme.violet)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(account?.email ?? "Codex 账号信息加载中")
                        .font(.system(size: 12, weight: .medium)).foregroundStyle(.white)
                        .lineLimit(1).truncationMode(.middle)
                    Text(account?.authType == "chatgpt" ? "ChatGPT 登录" : "Codex 账号")
                        .font(.system(size: 10)).foregroundStyle(Theme.muted)
                }
                Spacer()
                Text((account?.planType ?? "未知套餐").uppercased())
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(Theme.cyan)
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(Theme.cyan.opacity(0.12), in: Capsule())
            }
        }
    }

    private var hero: some View {
        let visual = modelVisual(current?.model)
        return GlassCard {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.snapshot?.selectionMode == "desktop_view" ? "当前查看的会话" : "最近会话")
                        .font(.system(size: 10, weight: .bold, design: .monospaced))
                        .tracking(2).foregroundStyle(Theme.cyan)
                    HStack(spacing: 9) {
                        Image(systemName: visual.symbol).foregroundStyle(visual.color)
                            .font(.system(size: 24))
                            .accessibilityLabel(visual.label)
                        Text(current?.model?.uppercased() ?? "等待会话")
                            .font(.system(size: 25, weight: .bold, design: .rounded)).foregroundStyle(.white)
                            .lineLimit(1).minimumScaleFactor(0.7)
                    }
                    Text("思考：\(effortLabel(current?.effort))  ·  \((current?.provider ?? "—").uppercased())")
                        .font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.muted)
                }
                Spacer()
                Text(statusLabel)
                    .font(.system(size: 10, weight: .semibold))
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background((isRunning ? Theme.lime : Theme.muted).opacity(0.15), in: Capsule())
                    .foregroundStyle(isRunning ? Theme.lime : Theme.muted)
            }
            if let title = current?.title {
                Text(title).font(.system(size: 12, weight: .medium)).foregroundStyle(.white.opacity(0.85))
                    .lineLimit(2)
            }
            Divider().overlay(Theme.border).padding(.vertical, 8)
            HStack(spacing: 7) {
                Image(systemName: "folder.fill").foregroundStyle(Theme.violet)
                Text(current?.cwd ?? "暂无工作目录").lineLimit(1).truncationMode(.middle)
            }
            .font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.muted)
            HStack {
                Text("会话累计 \(compact(current?.usage.totalTokens ?? 0)) tokens")
                Spacer()
                Text("更新于 \(clock(current?.updatedAt))")
            }
            .font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.muted.opacity(0.75))
            .padding(.top, 8)
            HStack {
                Text(current?.originator ?? "Codex")
                Spacer()
                if let started = current?.turnStartedAt, isRunning {
                    Text("本轮已运行 \(duration(Int((parseDate(model.snapshot?.updatedAt)?.timeIntervalSince1970 ?? Double(started)) * 1000) - started * 1000))")
                } else if let elapsed = current?.lastDurationMs {
                    Text("上一轮 \(duration(elapsed))")
                }
            }
            .font(.system(size: 10)).foregroundStyle(Theme.muted.opacity(0.75))
        }
    }

    private func effortLabel(_ effort: String?) -> String {
        switch effort {
        case "none": return "关闭"
        case "minimal": return "极低"
        case "low": return "低"
        case "medium": return "中"
        case "high": return "高"
        case "xhigh": return "超高"
        case "max": return "最大"
        case "ultra": return "极致"
        default: return "未知"
        }
    }

    private var contextCard: some View {
        let input = current?.lastInputTokens ?? 0
        let window = current?.contextWindow ?? 0
        let remaining = window > 0 ? max(0, 1 - Double(input) / Double(window)) : 0
        return GlassCard {
            HStack {
                Label("上下文剩余", systemImage: "circle.hexagongrid.fill")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                Spacer()
                Text(window > 0 ? "约 \(Int(remaining * 100))%" : "暂无数据")
                    .font(.system(size: 18, weight: .bold, design: .rounded)).foregroundStyle(Theme.cyan)
            }
            MeterBar(fraction: remaining, tint: Theme.cyan).padding(.vertical, 8)
            HStack {
                Text("最近请求输入 \(compact(input))")
                Spacer()
                Text("窗口 \(compact(window))")
            }
            .font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.muted)
            Text("按最近请求输入估算，非 Codex 精确上下文计数")
                .font(.system(size: 10)).foregroundStyle(Theme.muted.opacity(0.7)).padding(.top, 3)
        }
    }

    private var limitCard: some View {
        let rate = primaryRate
        let remaining = rate?.usedPercent.map { max(0, 100 - $0) }
        return GlassCard {
            HStack {
                Label("套餐额度剩余", systemImage: "gauge.with.dots.needle.67percent")
                    .font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                Spacer()
                Text(remaining.map { String(format: "%.0f%%", $0) } ?? "—")
                    .font(.system(size: 18, weight: .bold, design: .rounded)).foregroundStyle(Theme.violet)
            }
            MeterBar(fraction: (remaining ?? 0) / 100, tint: Theme.violet).padding(.vertical, 8)
            HStack {
                Text(rate?.minutes == 10_080 ? "7 天窗口" : "窗口 \(rate?.minutes ?? 0) 分钟")
                Spacer()
                Text("重置 \(resetTime(rate?.resetsAt))")
            }
            .font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.muted)
            Text(model.snapshot?.account?.stale == true || model.snapshot?.account == nil ? "账号额度暂不可用，等待刷新" : "ChatGPT 套餐窗口，非 token 或 API 余额")
                .font(.system(size: 10)).foregroundStyle(Theme.muted.opacity(0.7)).padding(.top, 3)
            if let secondary = model.snapshot?.account?.rateLimits?.secondary,
               let used = secondary.usedPercent {
                Text("第二窗口剩余 \(Int(max(0, 100 - used)))% · 重置 \(resetTime(secondary.resetsAt))")
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.muted)
            }
            if let credits = model.snapshot?.account?.rateLimits?.credits,
               credits.hasCredits == true {
                Text(credits.unlimited == true ? "积分：无限制" : "积分余额：\(credits.balance ?? "待更新")")
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.muted)
            }
        }
    }

    private var breakdownCard: some View {
        let usage = current?.usage
        let input = usage?.inputTokens ?? 0
        let output = usage?.outputTokens ?? 0
        let cached = usage?.cachedInputTokens ?? 0
        return GlassCard {
            Text("会话用量构成").font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
            HStack {
                breakdown("输入", compact(input), Theme.cyan)
                breakdown("缓存输入", compact(cached), Theme.violet)
                breakdown("输出", compact(output), Theme.lime)
            }
            .padding(.top, 7)
            Text("输入含缓存输入；输出含推理输出 \(compact(usage?.reasoningOutputTokens ?? 0))")
                .font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.muted)
                .padding(.top, 8)
        }
    }

    private func breakdown(_ title: String, _ value: String, _ tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) { Circle().fill(tint).frame(width: 5, height: 5); Text(title) }
                .font(.system(size: 10)).foregroundStyle(Theme.muted)
            Text(value).font(.system(size: 17, weight: .semibold, design: .rounded)).foregroundStyle(.white)
                .lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func trendCard(_ points: [DailyPoint]) -> some View {
        let maximum = max(points.map(\.totalTokens).max() ?? 1, 1)
        return GlassCard {
            HStack {
                Text("本机 Token 趋势").font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
                Spacer()
                Button("7 天") { showMonthTrend = false; hoveredDay = nil }
                    .foregroundStyle(showMonthTrend ? Theme.muted : Theme.cyan)
                Button("本月") { showMonthTrend = true; hoveredDay = nil }
                    .foregroundStyle(showMonthTrend ? Theme.cyan : Theme.muted)
            }
            .buttonStyle(.plain)
            HStack {
                if let point = hoveredDay {
                    Text(point.date).foregroundStyle(Theme.muted)
                    Spacer()
                    Text("\(point.totalTokens.formatted()) tokens")
                        .fontWeight(.semibold).foregroundStyle(Theme.cyan)
                } else {
                    Text("悬停柱形查看每日用量").foregroundStyle(Theme.muted)
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
                                .fill(LinearGradient(colors: [Theme.cyan, Theme.violet], startPoint: .top, endPoint: .bottom))
                                .opacity(hoveredDay == nil || hoveredDay?.id == point.id ? 1 : 0.5)
                                .shadow(color: hoveredDay?.id == point.id ? Theme.cyan.opacity(0.65) : .clear, radius: 5)
                                .frame(height: max(5, 64 * CGFloat(point.totalTokens) / CGFloat(maximum)))
                            if points.count <= 7 {
                                Text(String(point.date.suffix(2)))
                                    .font(.system(size: 9, design: .monospaced)).foregroundStyle(Theme.muted)
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
                    Text("1 日")
                    Spacer()
                    Text("15 日")
                    Spacer()
                    Text("\(points.count) 日")
                }
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(Theme.muted)
            }
        }
    }

    private func sessionsCard(_ sessions: [Session]) -> some View {
        GlassCard {
            Text("最近会话").font(.system(size: 12, weight: .semibold)).foregroundStyle(.white)
            ForEach(sessions.prefix(4)) { session in
                HStack(spacing: 8) {
                    Circle().fill(session.taskStatus == "running" ? Theme.lime : Theme.muted.opacity(0.6))
                        .frame(width: 6, height: 6)
                    Text(session.model ?? "未知模型").foregroundStyle(.white)
                    Spacer()
                    Text(compact(session.usage.totalTokens)).foregroundStyle(Theme.cyan)
                    Text(clock(session.updatedAt)).foregroundStyle(Theme.muted)
                }
                .font(.system(size: 10, design: .monospaced))
                .padding(.top, 6)
            }
        }
    }

    private var footer: some View {
        HStack {
            Text(model.updateMessage ?? (model.error == nil ? (model.snapshot?.selectionMode == "desktop_view" ? "跟随 Codex 窗口 · 约每 2 秒刷新" : "按最近活动显示 · 约每 2 秒刷新") : "读取异常：\(model.error ?? "")"))
                .lineLimit(1).foregroundStyle(Theme.muted)
            Spacer()
            Button(action: checkUpdate) { Image(systemName: "arrow.down.circle") }
                .buttonStyle(.plain).help("检查更新")
            Button(action: refresh) { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.plain).help("立即刷新")
            Button(action: quit) { Image(systemName: "power") }
                .buttonStyle(.plain).help("退出")
        }
        .font(.system(size: 10)).foregroundStyle(Theme.muted)
        .padding(.horizontal, 3)
    }
}

private final class PulsePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class CodexPulseApp: NSObject, NSApplicationDelegate {
    private let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var panel: PulsePanel?
    private var globalClickMonitor: Any?
    private var localEventMonitor: Any?
    private let model = DashboardModel()
    private let logo = StatusIconRenderer()
    private var inFlight = false
    private var updateCheckInFlight = false
    private var previewWindow: NSWindow?
    private var currentVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.0.0"
    }
    private lazy var pythonExecutable: URL? = {
        let environment = ProcessInfo.processInfo.environment
        #if arch(arm64)
        let preferred = ["/opt/homebrew/bin/python3", "/usr/bin/python3", "/usr/local/bin/python3"]
        #else
        let preferred = ["/usr/local/bin/python3", "/usr/bin/python3", "/opt/homebrew/bin/python3"]
        #endif
        let fromPath = (environment["PATH"] ?? "").split(separator: ":").map { "\($0)/python3" }
        for path in ([environment["CODEX_PULSE_PYTHON"]].compactMap { $0 } + preferred + fromPath) {
            if FileManager.default.isExecutableFile(atPath: path) { return URL(fileURLWithPath: path) }
        }
        return nil
    }()

    private func showMenuStatus(_ state: String, iconState: String, remaining: Int?) {
        let font = NSFont.systemFont(ofSize: 11, weight: .medium)
        let numberFont = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .semibold)
        let text = NSMutableAttributedString()
        if let remaining {
            text.append(NSAttributedString(string: "剩余 ", attributes: [
                .font: font, .foregroundColor: NSColor.labelColor
            ]))
            text.append(NSAttributedString(string: "\(remaining)%", attributes: [
                .font: numberFont, .foregroundColor: NSColor.labelColor
            ]))
        } else {
            text.append(NSAttributedString(string: "额度未知", attributes: [
                .font: font, .foregroundColor: NSColor.labelColor
            ]))
        }
        let icon = logo.image(for: iconState)
        status.button?.image = icon
        model.statusIcon = icon
        status.button?.attributedTitle = text
        status.button?.toolTip = remaining.map { "Codex Pulse · \(state) · 套餐额度剩余 \($0)%" } ?? "Codex Pulse · \(state)"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        status.button?.imagePosition = .imageLeft
        showMenuStatus("加载中", iconState: "idle", remaining: nil)
        status.button?.target = self
        status.button?.action = #selector(togglePanel)
        let panel = PulsePanel(contentRect: NSRect(x: 0, y: 0, width: 430, height: 690),
                               styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Codex Pulse"
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
            quit: { NSApplication.shared.terminate(nil) }))
        self.panel = panel
        let isPreview = ProcessInfo.processInfo.environment["CODEX_PULSE_PREVIEW"] == "1"
        if isPreview {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 430, height: 690),
                                  styleMask: [.titled, .closable], backing: .buffered, defer: false)
            window.title = "Codex Pulse Preview"
            window.contentView = NSHostingView(rootView: DashboardView(
                model: model, refresh: { [weak self] in self?.refreshNow() },
                checkUpdate: { [weak self] in self?.checkForUpdates(manual: true) },
                installUpdate: { [weak self] in self?.installUpdate() },
                quit: { NSApplication.shared.terminate(nil) }))
            window.center()
            window.makeKeyAndOrderFront(nil)
            NSApplication.shared.activate(ignoringOtherApps: true)
            previewWindow = window
        }
        refreshNow()
        readUpdateStatus()
        if isPreview && ProcessInfo.processInfo.environment["CODEX_PULSE_PREVIEW_UPDATE"] == "1" {
            model.updateInfo = UpdateInfo(available: true, latestVersion: "0.1.5",
                                          releaseUrl: "https://github.com/xushanpei/codex-pulse/releases")
        } else {
            checkForUpdates()
        }
        if ProcessInfo.processInfo.environment["CODEX_PULSE_SHOW_PANEL"] == "1" {
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
            .appendingPathComponent(".codex/codex-pulse/update-status.json")
        if let data = try? Data(contentsOf: path),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: String],
           let message = value["message"] {
            model.updateMessage = message
            try? FileManager.default.removeItem(at: path)
        }
    }

    @objc private func checkUpdatesTimer() { checkForUpdates() }

    private func checkForUpdates(manual: Bool = false) {
        guard !updateCheckInFlight else { return }
        guard let pythonExecutable else {
            if manual { model.updateMessage = "未找到 Python 3，无法检查更新" }
            return
        }
        updateCheckInFlight = true
        if manual { model.updateMessage = "正在检查更新…" }
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
                if process.terminationStatus != 0 { throw NSError(domain: "CodexPulseUpdate", code: Int(process.terminationStatus)) }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                update = try decoder.decode(UpdateInfo.self, from: data)
            } catch { readError = error.localizedDescription }
            DispatchQueue.main.async {
                self?.model.updateInfo = update?.available == true ? update : nil
                if manual {
                    self?.model.updateMessage = readError == nil ?
                        (update?.available == true ? "发现新版本 \(update?.latestVersion ?? "")" : "已是最新版本") :
                        "检查更新失败，请稍后重试"
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
            model.updateMessage = "正在更新，完成后会重新启动…"
            try process.run()
            NSApplication.shared.terminate(nil)
        } catch {
            model.updateMessage = "无法启动更新程序：\(error.localizedDescription)"
        }
    }

    @objc private func togglePanel() {
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
        if ProcessInfo.processInfo.environment["CODEX_PULSE_PREVIEW"] == "1" { return }
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
            model.error = "未找到 Python 3，请安装 Python 3 或 Xcode 命令行工具"
            showMenuStatus("读取异常", iconState: "error", remaining: nil)
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
                if process.terminationStatus != 0 { throw NSError(domain: "CodexPulse", code: Int(process.terminationStatus)) }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                snapshot = try decoder.decode(Snapshot.self, from: data)
            } catch { readError = error.localizedDescription }
            DispatchQueue.main.async {
                if let snapshot {
                    self?.model.snapshot = snapshot
                    self?.model.error = nil
                    let session = snapshot.currentSession
                    let state = session?.taskStatus == "running" ? "运行中" : (session?.taskStatus == "unconfirmed" ? "待确认" : "空闲")
                    let iconState = session?.taskStatus == "running" ? "running" : (session?.taskStatus == "unconfirmed" ? "unconfirmed" : "idle")
                    let quota = snapshot.account?.stale == false ? snapshot.account?.rateLimits?.primary : nil
                    self?.showMenuStatus(state, iconState: iconState,
                                         remaining: quota?.usedPercent.map { Int(max(0, 100 - $0)) })
                } else {
                    self?.model.error = readError ?? "未知错误"
                    self?.showMenuStatus("状态未知", iconState: "error", remaining: nil)
                }
                self?.inFlight = false
            }
        }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = CodexPulseApp()
app.delegate = delegate
app.run()
