import UIKit
import Capacitor
import UserNotifications

// The red number on the app icon. The page sets it (to 0 when the app opens); Apple's push sets it
// when an alert arrives.
@objc(SidelineApp)
public class SidelineApp: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "SidelineApp"
    public let jsName = "SidelineApp"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "setBadge", returnType: CAPPluginReturnPromise)
    ]

    @objc func setBadge(_ call: CAPPluginCall) {
        let n = max(0, call.getInt("n") ?? 0)
        DispatchQueue.main.async {
            if #available(iOS 16.0, *) {
                UNUserNotificationCenter.current().setBadgeCount(n) { _ in call.resolve() }
            } else {
                UIApplication.shared.applicationIconBadgeNumber = n
                call.resolve()
            }
        }
    }
}
