import api from "./client";
import type { Lead, PaginatedResponse } from "@/types";

export interface LeadListParams {
  stage?: string;
  bucket?: string;
  owner?: string;
  q?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export async function listLeads(params: LeadListParams = {}): Promise<PaginatedResponse<Lead>> {
  const { data } = await api.get<PaginatedResponse<Lead>>("/leads", { params });
  return data;
}

export async function getLead(id: string): Promise<Lead> {
  const { data } = await api.get<Lead>(`/leads/${id}`);
  return data;
}

export async function createLead(input: Partial<Lead>): Promise<Lead> {
  const { data } = await api.post<Lead>("/leads", input);
  return data;
}

export async function updateLead(id: string, input: Partial<Lead>): Promise<Lead> {
  const { data } = await api.patch<Lead>(`/leads/${id}`, input);
  return data;
}

export async function deleteLead(id: string): Promise<void> {
  await api.delete(`/leads/${id}`);
}

export async function advanceLeadStage(id: string): Promise<Lead> {
  const { data } = await api.post<Lead>(`/leads/${id}/advance`);
  return data;
}

export async function suppressLead(id: string, reason?: string): Promise<void> {
  await api.post(`/leads/${id}/suppress`, { reason });
}
