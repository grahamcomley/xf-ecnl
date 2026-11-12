import UIKit
import Capacitor

// A plugin inside the app target isn't found by Capacitor on its own; handing it to the bridge here
// registers it. CI points Main.storyboard at this class (same fix as Hashmark).
class AppViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(SidelineApp())
    }
}
