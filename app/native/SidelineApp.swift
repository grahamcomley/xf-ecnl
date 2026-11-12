import UIKit
import Capacitor
import UserNotifications
import AuthenticationServices

// Native bits the page asks for:
//   setBadge({n})       the red number on the app icon (0 when the app opens; Apple's push sets it on arrival)
//   signIn({url, scheme}) the iPhone's own sign-in sheet. It shares Safari, so saved Google logins and
//                        passwords work and Sign in with Apple uses Face ID. Resolves {url} with the
//                        sideline://signin?ticket=... address the sign-in page finishes on, or {cancelled: true}.
@objc(SidelineApp)
public class SidelineApp: CAPPlugin, CAPBridgedPlugin, ASWebAuthenticationPresentationContextProviding {
    public let identifier = "SidelineApp"
    public let jsName = "SidelineApp"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "setBadge", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "signIn", returnType: CAPPluginReturnPromise)
    ]
    private var authSession: ASWebAuthenticationSession?

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

    @objc func signIn(_ call: CAPPluginCall) {
        guard let s = call.getString("url"), let url = URL(string: s) else { call.reject("bad url"); return }
        let scheme = call.getString("scheme") ?? "sideline"
        DispatchQueue.main.async {
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { [weak self] cb, err in
                self?.authSession = nil
                if let cb = cb {
                    if URLComponents(url: cb, resolvingAgainstBaseURL: false)?.queryItems?.contains(where: { $0.name == "cancel" }) == true {
                        call.resolve(["cancelled": true])
                    } else {
                        call.resolve(["url": cb.absoluteString])
                    }
                } else if let e = err as? ASWebAuthenticationSessionError, e.code == .canceledLogin {
                    call.resolve(["cancelled": true])
                } else {
                    call.reject(err?.localizedDescription ?? "sign-in failed")
                }
            }
            session.presentationContextProvider = self
            session.prefersEphemeralWebBrowserSession = false   // share Safari's saved sign-ins
            self.authSession = session
            if !session.start() { self.authSession = nil; call.reject("could not open sign-in") }
        }
    }

    public func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        return self.bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
