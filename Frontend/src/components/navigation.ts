export type NavIconName = 'overview' | 'system' | 'account' | 'accounts' | 'session' | 'collapse' | 'signout' | 'refresh'

export interface NavItem {
  id: string
  label: string
  icon: NavIconName
}

export interface NavGroup {
  label: string
  items: NavItem[]
}
