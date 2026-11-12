export type NavIconName = 'overview' | 'system' | 'machines' | 'account' | 'accounts' | 'session' | 'collapse' | 'signout' | 'refresh' | 'bell'

export interface NavItem {
  id: string
  label: string
  icon: NavIconName
}

export interface NavGroup {
  label: string
  items: NavItem[]
}
