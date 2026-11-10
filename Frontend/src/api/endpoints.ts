import { api } from './client'
import type {
  HealthResponse,
  LoginRequest,
  LoginResponse,
  RegisterUserRequest,
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

export async function listUsers(signal?: AbortSignal): Promise<UserResponse[]> {
  const { data } = await api.get<UserResponse[]>('/users', { signal })
  return data
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/health', { signal })
  return data
}
