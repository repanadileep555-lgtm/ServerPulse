import { api } from './client'
import type {
  ChangePasswordRequest,
  HealthResponse,
  LoginRequest,
  LoginResponse,
  RegisterUserRequest,
  UpdateProfileRequest,
  UserResponse,
} from './types'

export async function login(body: LoginRequest): Promise<LoginResponse> {
  const { data } = await api.post<LoginResponse>('/users/login', body)
  return data
}

export async function createUser(body: RegisterUserRequest): Promise<UserResponse> {
  const { data } = await api.post<UserResponse>('/users/create', body)
  return data
}

export async function createAdmin(body: RegisterUserRequest): Promise<UserResponse> {
  const { data } = await api.post<UserResponse>('/users/admins', body)
  return data
}

export async function getCurrentUser(signal?: AbortSignal): Promise<UserResponse> {
  const { data } = await api.get<UserResponse>('/users/me', { signal })
  return data
}

export async function updateProfile(body: UpdateProfileRequest): Promise<UserResponse> {
  const { data } = await api.patch<UserResponse>('/users/me', body)
  return data
}

export async function changePassword(body: ChangePasswordRequest): Promise<void> {
  await api.post('/users/me/password', body)
}

export async function listUsers(signal?: AbortSignal): Promise<UserResponse[]> {
  const { data } = await api.get<UserResponse[]>('/users', { signal })
  return data
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health', { signal })
  return data
}
