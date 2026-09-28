import CoreText
import Foundation

let fontDir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Fonts")
let names = (try? FileManager.default.contentsOfDirectory(at: fontDir, includingPropertiesForKeys: nil)) ?? []
let meslo = names.filter {
    let n = $0.lastPathComponent
    return n.hasPrefix("MesloLGSNerdFont") && n.hasSuffix(".ttf")
        && !n.contains("DZ") && !n.contains("Mono") && !n.contains("Propo")
}

guard !meslo.isEmpty else {
    fputs("no MesloLGS Nerd Font ttf in \(fontDir.path)\n", stderr)
    exit(1)
}

var failed = false
for url in meslo {
    var err: Unmanaged<CFError>?
    let ok = CTFontManagerRegisterFontsForURL(url as CFURL, .user, &err)
    let detail = err?.takeRetainedValue().localizedDescription ?? ""
    if ok {
        print("registered \(url.lastPathComponent)")
    } else {
        fputs("failed \(url.lastPathComponent): \(detail)\n", stderr)
        failed = true
    }
}

if let families = CTFontManagerCopyAvailableFontFamilyNames() as? [String],
   families.contains(where: { $0 == "MesloLGS Nerd Font" }) {
    print("family MesloLGS Nerd Font")
} else {
    fputs("family MesloLGS Nerd Font not visible to CoreText\n", stderr)
    failed = true
}

exit(failed ? 1 : 0)
