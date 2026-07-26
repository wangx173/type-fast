// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "TypeFastIME",
    platforms: [.macOS(.v13)],
    products: [
        .library(name: "TypeFastIME", targets: ["TypeFastIME"])
    ],
    targets: [
        .target(name: "TypeFastIME"),
        .testTarget(name: "TypeFastIMETests", dependencies: ["TypeFastIME"]),
    ]
)
