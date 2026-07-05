import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
// eslint-disable-next-line no-restricted-imports
import { get, post } from '@/service/base'

export type WorkspaceContact = {
  id: string
  tenant_id: string
  type: 'member' | 'external'
  status: 'active' | 'disabled'
  source: string
  account_id: string | null
  name: string
  email: string | null
  delivery_status: 'im' | 'email' | 'none'
  delivery_provider: string | null
}

type ContactsResponse = {
  data: WorkspaceContact[]
}

const contactsQueryKey = ['workspace-contacts', 'current'] as const

export const contactsQueryOptions = () =>
  queryOptions<WorkspaceContact[]>({
    queryKey: contactsQueryKey,
    queryFn: async () => {
      const response = await get<ContactsResponse>('/workspaces/current/contacts')
      return response.data
    },
  })

export const useContacts = () => {
  return useQuery(contactsQueryOptions())
}

export const useCreateExternalContact = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationKey: ['workspace-contacts', 'create-external'],
    mutationFn: (body: { name: string, email: string }) => {
      return post<WorkspaceContact>('/workspaces/current/contacts', { body })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: contactsQueryKey })
    },
  })
}
