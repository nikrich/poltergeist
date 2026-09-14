import Foundation

/// 64×36 grayscale thumbnail used for cheap frame-to-frame comparison.
public struct Thumbnail: Equatable, Sendable {
    public static let width = 64
    public static let height = 36

    /// Row-major luminance in 0...1, `width * height` entries.
    public var pixels: [Float]

    public init(pixels: [Float]) {
        precondition(pixels.count == Self.width * Self.height, "thumbnail must be \(Self.width)x\(Self.height)")
        self.pixels = pixels
    }

    public init(fill: Float) {
        pixels = [Float](repeating: fill, count: Self.width * Self.height)
    }

    /// Build from a packed 32-bit BGRA buffer (SCStream `kCVPixelFormatType_32BGRA`).
    /// Each thumbnail cell averages up to 4×4 evenly spaced source pixels of its
    /// block, so cost is independent of the frame size.
    public static func fromBGRA(_ base: UnsafeRawPointer, width: Int, height: Int, bytesPerRow: Int) -> Thumbnail {
        var out = [Float](repeating: 0, count: Self.width * Self.height)
        guard width > 0, height > 0 else { return Thumbnail(pixels: out) }
        let bytes = base.assumingMemoryBound(to: UInt8.self)
        let samplesPerAxis = 4
        for ty in 0..<Self.height {
            let y0 = ty * height / Self.height
            let y1 = max(y0 + 1, (ty + 1) * height / Self.height)
            for tx in 0..<Self.width {
                let x0 = tx * width / Self.width
                let x1 = max(x0 + 1, (tx + 1) * width / Self.width)
                var acc: Float = 0
                var n = 0
                let ys = min(samplesPerAxis, y1 - y0)
                let xs = min(samplesPerAxis, x1 - x0)
                for sy in 0..<ys {
                    let y = y0 + (y1 - y0) * sy / ys
                    let row = y * bytesPerRow
                    for sx in 0..<xs {
                        let x = x0 + (x1 - x0) * sx / xs
                        let p = row + x * 4
                        let b = Float(bytes[p]), g = Float(bytes[p + 1]), r = Float(bytes[p + 2])
                        acc += (0.114 * b + 0.587 * g + 0.299 * r) / 255.0
                        n += 1
                    }
                }
                out[ty * Self.width + tx] = n > 0 ? acc / Float(n) : 0
            }
        }
        return Thumbnail(pixels: out)
    }
}

public enum FrameDiff {
    /// Mean absolute luminance difference in 0...1.
    public static func meanAbsDiff(_ a: Thumbnail, _ b: Thumbnail) -> Double {
        var acc: Double = 0
        for i in 0..<a.pixels.count {
            acc += Double(abs(a.pixels[i] - b.pixels[i]))
        }
        return acc / Double(a.pixels.count)
    }
}
