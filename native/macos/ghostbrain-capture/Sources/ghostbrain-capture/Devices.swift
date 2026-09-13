import AVFoundation
import Foundation

struct AudioInputDevice: Encodable {
    let id: String
    let name: String
    let isDefault: Bool
    enum CodingKeys: String, CodingKey { case id, name, isDefault = "default" }
}

@available(macOS 14, *)
enum Devices {
    static func listInputs() -> [AudioInputDevice] {
        let session = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external], mediaType: .audio, position: .unspecified)
        let defaultID = AVCaptureDevice.default(for: .audio)?.uniqueID
        return session.devices.map {
            AudioInputDevice(id: $0.uniqueID, name: $0.localizedName, isDefault: $0.uniqueID == defaultID)
        }
    }

    static func json(_ devices: [AudioInputDevice]) -> String {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let data = (try? enc.encode(["devices": devices])) ?? Data("{\"devices\":[]}".utf8)
        return String(decoding: data, as: UTF8.self)
    }
}
