import AppKit
import Combine
import CryptoKit
import SwiftUI
import UniformTypeIdentifiers
import WebKit

final class LineDecoder {
    private let lock = NSLock()
    private var pending = Data()
    func append(_ data: Data) -> [String] {
        lock.lock(); defer { lock.unlock() }
        pending.append(data)
        var lines: [String] = []
        while let index = pending.firstIndex(where: { $0 == 10 || $0 == 13 }) {
            lines.append(String(decoding: pending[..<index], as: UTF8.self))
            pending.removeSubrange(...index)
        }
        return lines
    }
}

@MainActor final class DesktopEngine: ObservableObject {
    @Published var stage = "Preparing local speech engine"
    @Published var detail = ""
    @Published var progress: Double? = nil
    @Published var serverURL: URL?
    @Published var error: String?
    @Published var running = false
    @Published var workspace: URL
    private var process: Process?
    private var cancelled = false
    private var finishingQuit = false
    private var lastProgressLog = Date.distantPast
    private let resources = Bundle.main.resourceURL!
    private var backend: URL { resources.appendingPathComponent("Backend") }
    private var python: URL { workspace.appendingPathComponent("Runtime/venv/bin/python") }
    private var uv: URL { resources.appendingPathComponent("bin/uv") }

    init() {
        let override = ProcessInfo.processInfo.environment["DUBBING_DESKTOP_WORKSPACE"]
        let stored = UserDefaults.standard.string(forKey: "workspace")
        workspace = URL(fileURLWithPath: override ?? stored ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("LocalDub").path, isDirectory: true)
    }

    func log(_ line: String) {
        let isProgress = line.contains("\"model_progress\"")
        if !isProgress || Date().timeIntervalSince(lastProgressLog) > 15 {
            let path = workspace.appendingPathComponent("Runtime/setup.log")
            if !FileManager.default.fileExists(atPath: path.path) { FileManager.default.createFile(atPath: path.path, contents: nil) }
            if let handle = try? FileHandle(forWritingTo: path) {
                defer { try? handle.close() }
                try? handle.seekToEnd(); try? handle.write(contentsOf: Data((line + "\n").utf8))
            }
            if isProgress { lastProgressLog = Date() }
        }
        if let data = line.data(using: .utf8), let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let kind = event["event"] as? String {
            if kind == "server_ready", let address = event["url"] as? String {
                serverURL = URL(string: address); stage = "Ready"; progress = 1
            } else if kind == "model_progress", let done = event["completed_bytes"] as? Double, let total = event["total_bytes"] as? Double, total > 0 {
                progress = 0.35 + 0.6 * min(1, done / total)
                detail = "Models: \(ByteCountFormatter.string(fromByteCount: Int64(done), countStyle: .file)) / \(ByteCountFormatter.string(fromByteCount: Int64(total), countStyle: .file))"
            } else if kind == "model_start" {
                stage = "Downloading speech models"
            } else if kind == "model_verify" {
                stage = "Verifying downloaded model"
            }
        } else if !line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            detail = String(line.suffix(300))
        }
    }

    private func environment() -> [String: String] {
        let inherited = ProcessInfo.processInfo.environment
        var result: [String: String] = [:]
        for key in ["HOME", "USER", "LOGNAME", "LANG", "LC_ALL"] { result[key] = inherited[key] }
        result["PATH"] = resources.appendingPathComponent("bin").path + ":/usr/bin:/bin:/usr/sbin:/sbin"
        result["PYTHONPATH"] = backend.path
        result["PYTHONDONTWRITEBYTECODE"] = "1"
        result["PYTHONUNBUFFERED"] = "1"
        result["DUBBING_DESKTOP_WORKSPACE"] = workspace.path
        result["DUBBING_HOME"] = workspace.appendingPathComponent("Jobs").path
        result["HF_HOME"] = workspace.appendingPathComponent("Models").path
        result["HF_HUB_DISABLE_XET"] = "1"
        result["UV_CACHE_DIR"] = workspace.appendingPathComponent("Cache/uv").path
        result["UV_PYTHON_INSTALL_DIR"] = workspace.appendingPathComponent("Runtime/python").path
        result["UV_PYTHON_BIN_DIR"] = workspace.appendingPathComponent("Runtime/bin").path
        result["UV_PYTHON_INSTALL_BIN"] = "0"
        result["NUMBA_CACHE_DIR"] = workspace.appendingPathComponent("Cache/numba").path
        result["MPLCONFIGDIR"] = workspace.appendingPathComponent("Cache/matplotlib").path
        result["TMPDIR"] = workspace.appendingPathComponent("Cache/tmp").path
        return result
    }

    private func command(_ executable: URL, _ arguments: [String]) async throws {
        if cancelled { throw CancellationError() }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let task = Process(); let pipe = Pipe(); let decoder = LineDecoder()
            task.executableURL = executable; task.arguments = arguments
            task.environment = environment(); task.currentDirectoryURL = backend
            task.standardOutput = pipe; task.standardError = pipe
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                for line in decoder.append(data) { Task { @MainActor in self?.log(line) } }
            }
            task.terminationHandler = { [weak self] finished in
                pipe.fileHandleForReading.readabilityHandler = nil
                let tail = pipe.fileHandleForReading.readDataToEndOfFile()
                let lines = decoder.append(tail + Data([10]))
                Task { @MainActor in
                    for line in lines { self?.log(line) }
                    self?.process = nil
                    if self?.finishingQuit == true { NSApp.reply(toApplicationShouldTerminate: true) }
                    if finished.terminationStatus == 0 { continuation.resume() }
                    else { continuation.resume(throwing: NSError(domain: "PodcastDubbing", code: Int(finished.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "\(executable.lastPathComponent) stopped (\(finished.terminationStatus)). \(self?.detail ?? "")"])) }
                }
            }
            do { try task.run(); process = task }
            catch { pipe.fileHandleForReading.readabilityHandler = nil; continuation.resume(throwing: error) }
        }
    }

    func start() {
        guard !running else { return }
        running = true; cancelled = false; error = nil; serverURL = nil
        Task {
            do {
                let fm = FileManager.default
                let selected = UserDefaults.standard.string(forKey: "workspace") != nil || ProcessInfo.processInfo.environment["DUBBING_DESKTOP_WORKSPACE"] != nil
                if selected && !fm.fileExists(atPath: workspace.path) {
                    throw NSError(domain: "PodcastDubbing", code: 1, userInfo: [NSLocalizedDescriptionKey: "Selected storage is unavailable. Reconnect it or choose another folder."])
                }
                try fm.createDirectory(at: workspace, withIntermediateDirectories: true)
                if !fm.isWritableFile(atPath: workspace.path) { throw NSError(domain: "PodcastDubbing", code: 4, userInfo: [NSLocalizedDescriptionKey: "Selected storage folder is not writable. Choose another folder."]) }
                for name in ["Runtime", "Models", "Jobs", "Exports", "Cache/uv", "Cache/numba", "Cache/matplotlib", "Cache/tmp"] {
                    try fm.createDirectory(at: workspace.appendingPathComponent(name), withIntermediateDirectories: true)
                }
                if !fm.fileExists(atPath: workspace.appendingPathComponent("Runtime/models-ready.json").path) {
                    let free = (try fm.attributesOfFileSystem(forPath: workspace.path)[.systemFreeSize] as? NSNumber)?.int64Value ?? 0
                    if free < 25 * 1024 * 1024 * 1024 { throw NSError(domain: "PodcastDubbing", code: 2, userInfo: [NSLocalizedDescriptionKey: "First setup needs at least 25 GB of free space for packages, models and temporary files. Choose another folder or free space."]) }
                }
                let requirements = backend.appendingPathComponent("dubbing/requirements-tested.txt")
                let hash = SHA256.hash(data: try Data(contentsOf: requirements)).map { String(format: "%02x", $0) }.joined()
                let receipt = workspace.appendingPathComponent("Runtime/packages-ready.txt")
                if !fm.fileExists(atPath: python.path) {
                    stage = "1 of 4 · Installing private Python runtime"; progress = 0.05
                    try await command(uv, ["--no-config", "python", "install", "3.11.15", "--no-bin"])
                    try await command(uv, ["--no-config", "venv", "--python", "3.11.15", "--managed-python", workspace.appendingPathComponent("Runtime/venv").path])
                }
                if (try? String(contentsOf: receipt, encoding: .utf8)) != hash {
                    stage = "2 of 4 · Installing packages"; progress = 0.15
                    try await command(uv, ["--no-config", "pip", "install", "--python", python.path, "-r", requirements.path])
                    try await command(uv, ["--no-config", "pip", "check", "--python", python.path])
                    try hash.write(to: receipt, atomically: true, encoding: .utf8)
                }
                stage = "3 of 4 · Preparing local models"; progress = 0.35
                try await command(python, ["-B", "-u", "-m", "dubbing.desktop.bootstrap", "--workspace", workspace.path])
                stage = "4 of 4 · Starting local engine"; progress = 0.98
                try await command(python, ["-B", "-u", "-m", "dubbing.desktop.service"])
                if !cancelled { throw NSError(domain: "PodcastDubbing", code: 3, userInfo: [NSLocalizedDescriptionKey: "The local engine stopped. Retry to restart it; existing jobs are retained."]) }
            } catch {
                if !cancelled { self.error = error.localizedDescription; stage = "Setup or engine needs attention" }
            }
            running = false; serverURL = nil
            if cancelled { stage = "Stopped · completed work retained"; progress = nil }
        }
    }

    func stop() { cancelled = true; stage = "Stopping · retaining completed work"; if process?.isRunning == true { process?.terminate() } }
    func quit() -> NSApplication.TerminateReply {
        guard process != nil else { return .terminateNow }
        finishingQuit = true; stop(); return .terminateLater
    }
    func chooseStorage() {
        guard !running else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = true; panel.allowsMultipleSelection = false
        panel.message = "Choose a folder for models, jobs and exported podcasts. Existing data will stay in its current folder."
        if panel.runModal() == .OK, let url = panel.url {
            workspace = url; UserDefaults.standard.set(url.path, forKey: "workspace"); start()
        }
    }
    func openExports() { NSWorkspace.shared.open(workspace.appendingPathComponent("Exports")) }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var engine: DesktopEngine?
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply { engine?.quit() ?? .terminateNow }
}

struct LocalWebView: NSViewRepresentable {
    let url: URL
    let workspace: URL
    func makeCoordinator() -> Coordinator { Coordinator(url: url, workspace: workspace) }
    func makeNSView(context: Context) -> WKWebView {
        let web = WKWebView(); web.navigationDelegate = context.coordinator; web.uiDelegate = context.coordinator
        web.load(URLRequest(url: url)); return web
    }
    func updateNSView(_ web: WKWebView, context: Context) {}
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        let url: URL; let workspace: URL
        init(url: URL, workspace: URL) { self.url = url; self.workspace = workspace }
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let target = action.request.url, target.scheme == url.scheme, target.host == url.host, target.port == url.port else { decisionHandler(.cancel); return }
            decisionHandler(action.shouldPerformDownload ? .download : .allow)
        }
        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
        func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) { decisionHandler(response.canShowMIMEType ? .allow : .download) }
        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
            do {
                let folder = workspace.appendingPathComponent("Exports/Downloads"); try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let safe = URL(fileURLWithPath: suggestedFilename).lastPathComponent
                var target = folder.appendingPathComponent(safe)
                if FileManager.default.fileExists(atPath: target.path) { target = folder.appendingPathComponent(UUID().uuidString.prefix(8) + "-" + safe) }
                completionHandler(target)
            } catch { completionHandler(nil) }
        }
        func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
            let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = parameters.allowsMultipleSelection; panel.allowedContentTypes = [.audio]
            completionHandler(panel.runModal() == .OK ? panel.urls : nil)
        }
    }
}

@main struct PodcastDubbingApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var engine = DesktopEngine()
    var body: some Scene {
        WindowGroup("LocalDub") {
            VStack(spacing: 0) {
                HStack {
                    Text("LocalDub").font(.headline)
                    Spacer()
                    Button("Open Exports", action: engine.openExports)
                    Button(engine.running ? "Stop engine" : "Retry / Start") { engine.running ? engine.stop() : engine.start() }
                }.padding()
                Divider()
                if let url = engine.serverURL {
                    LocalWebView(url: url, workspace: engine.workspace)
                } else {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("Local podcast dubbing").font(.largeTitle)
                        Text("Mandarin and Spanish · Apple Silicon · macOS 26+").foregroundStyle(.secondary)
                        Text(engine.stage).font(.headline)
                        if let value = engine.progress { ProgressView(value: value) } else { ProgressView() }
                        Text(engine.detail).font(.system(.caption, design: .monospaced)).textSelection(.enabled).lineLimit(6)
                        if let error = engine.error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
                        Text("Storage: \(engine.workspace.path)").font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        Button("Choose storage folder", action: engine.chooseStorage).disabled(engine.running)
                        Text("First setup downloads the private runtime, packages and about 8 GB of models. Downloads resume on retry; completed jobs remain in the selected folder.").font(.callout).foregroundStyle(.secondary)
                    }.padding(40).frame(maxWidth: 700, maxHeight: .infinity)
                }
            }.frame(minWidth: 760, minHeight: 620)
                .onAppear { delegate.engine = engine; engine.start() }
        }.defaultSize(width: 960, height: 800)
    }
}
