Pod::Spec.new do |s|
  s.name = 'SidelineNative'
  s.version = '1.0.0'
  s.summary = 'Sideline Standings native bits'
  s.license = 'MIT'
  s.homepage = 'https://sidelinestandings.com'
  s.author = 'Sideline Standings'
  s.source = { :git => 'https://github.com/grahamcomley/xf-ecnl.git', :tag => s.version.to_s }
  s.source_files = 'ios/Sources/**/*.{swift,h,m}'
  s.ios.deployment_target = '15.0'
  s.dependency 'Capacitor'
  s.swift_version = '5.1'
end
