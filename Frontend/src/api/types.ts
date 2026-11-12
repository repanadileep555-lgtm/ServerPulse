export interface HealthResponse {
  database: 'ok' | 'error'
}

export interface UserResponse {
  id: number
  username: string
  display_name: string | null
  avatar: string | null
  is_admin: boolean
  enabled: boolean
  created_at: string
}

export interface UpdateProfileRequest {
  display_name?: string | null
  avatar?: string | null
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

export interface RegisterUserRequest {
  username: string
  password: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
}

export interface RefreshResponse {
  access_token: string
  token_type: 'bearer'
}
