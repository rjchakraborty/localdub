// Reproducible product artwork, rendered at every macOS icon size.
import AppKit

let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: true)

func render(_ pixels: Int, _ name: String) throws {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let context = NSGraphicsContext.current!.cgContext
    context.scaleBy(x: CGFloat(pixels)/1024, y: CGFloat(pixels)/1024)
    let tile = NSBezierPath(roundedRect: NSRect(x: 64, y: 64, width: 896, height: 896), xRadius: 200, yRadius: 200)
    NSGradient(starting: NSColor(srgbRed: 0.08, green: 0.70, blue: 0.62, alpha: 1),
        ending: NSColor(srgbRed: 0.07, green: 0.24, blue: 0.49, alpha: 1))!.draw(in: tile, angle: -70)
    // Two speech bubbles share a waveform: one voice, another language.
    NSColor.white.withAlphaComponent(0.16).setFill()
    NSBezierPath(roundedRect: NSRect(x: 300, y: 216, width: 524, height: 402), xRadius: 108, yRadius: 108).fill()
    let backTail = NSBezierPath(); backTail.move(to: NSPoint(x: 690, y: 262))
    backTail.line(to: NSPoint(x: 778, y: 170)); backTail.line(to: NSPoint(x: 780, y: 300)); backTail.close(); backTail.fill()
    NSColor.white.setFill()
    NSBezierPath(roundedRect: NSRect(x: 190, y: 342, width: 580, height: 410), xRadius: 112, yRadius: 112).fill()
    let tail = NSBezierPath(); tail.move(to: NSPoint(x: 230, y: 410))
    tail.line(to: NSPoint(x: 232, y: 280)); tail.line(to: NSPoint(x: 358, y: 374)); tail.close(); tail.fill()
    NSColor(srgbRed: 0.07, green: 0.42, blue: 0.48, alpha: 1).setFill()
    for (index, height) in [88, 168, 252, 168, 88].enumerated() {
        NSBezierPath(roundedRect: NSRect(x: CGFloat(298 + index*76), y: CGFloat(547-height/2), width: 38, height: CGFloat(height)), xRadius: 19, yRadius: 19).fill()
    }
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent(name))
}
for size in [16, 32, 128, 256, 512] {
    try render(size, "icon_\(size)x\(size).png")
    try render(size*2, "icon_\(size)x\(size)@2x.png")
}
