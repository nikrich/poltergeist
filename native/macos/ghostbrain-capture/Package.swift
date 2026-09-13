// swift-tools-version: 6.0
import PackageDescription

// Deployment target is deliberately 13.0, not 15.0: a binary whose minimum OS
// is 15 will not even launch on macOS 14 (dyld refuses it), which would make
// the documented "exit 3 = macOS < 15" contract unreachable. Everything that
// touches ScreenCaptureKit is gated behind `@available(macOS 15, *)` in the
// executable target; the Core library has no OS-version-specific API.
let package = Package(
    name: "ghostbrain-capture",
    platforms: [.macOS(.v13)],
    targets: [
        .target(
            name: "GhostbrainCaptureCore",
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
        .executableTarget(
            name: "ghostbrain-capture",
            dependencies: ["GhostbrainCaptureCore"],
            exclude: ["Info.plist"],
            swiftSettings: [.swiftLanguageMode(.v6)],
            linkerSettings: [
                // Embed Info.plist so TCC / codesign see a stable bundle id and
                // usage strings even when the helper runs outside Poltergeist.app.
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/ghostbrain-capture/Info.plist",
                ]),
            ]
        ),
        .testTarget(
            name: "GhostbrainCaptureCoreTests",
            dependencies: ["GhostbrainCaptureCore"],
            swiftSettings: [.swiftLanguageMode(.v6)]
        ),
    ]
)
