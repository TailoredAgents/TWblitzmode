import React from 'react'
import { render, screen, fireEvent, within } from '@testing-library/react'

import { TeamMembersTab } from '../app/admin/components/TeamMembersTab'
import type { TeamMember } from '../types'

const teamMembers: TeamMember[] = [
  {
    id: 1,
    name: 'Alex Admin',
    email: 'alex@tallwave.com',
    role: 'admin',
    status: 'active',
    created_at: '2024-09-01T12:00:00Z',
    cookie_status: 'valid',
    last_login_at: '2024-09-30T18:45:00Z',
  },
  {
    id: 2,
    name: 'Casey Collaborator',
    email: 'casey@tallwave.com',
    role: 'user',
    status: 'deactivated',
    created_at: '2024-09-05T12:00:00Z',
    cookie_status: 'missing',
    last_login_at: null,
  },
]

const statusBadgeClasses = {
  active: 'bg-green-500/20 text-green-600',
  deactivated: 'bg-slate-500/20 text-slate-600',
  valid: 'bg-green-500/20 text-green-600',
  missing: 'bg-amber-500/20 text-amber-600',
}

const formatRoleLabel = (role: string) => role.charAt(0).toUpperCase() + role.slice(1)
const formatDate = (value?: string | null) => (value ? 'Sep 30, 2024' : '—')

describe('TeamMembersTab actions', () => {
  const defaultProps = () => ({
    members: teamMembers,
    filteredMembers: teamMembers,
    statusFilter: 'all' as const,
    onStatusFilterChange: jest.fn(),
    searchQuery: '',
    onSearchChange: jest.fn(),
    roleOptions: ['admin', 'user'],
    formatRoleLabel,
    statusBadgeClasses,
    memberActionId: null,
    resettingMemberId: null,
    onRoleChange: jest.fn(),
    onToggleStatus: jest.fn(),
    onResetPassword: jest.fn(),
    formatDate,
  })

  it('renders Tallwave teammates and summary metadata', () => {
    const props = defaultProps()
    render(<TeamMembersTab {...props} />)

    expect(screen.getByText('Team Members')).toBeInTheDocument()
    expect(screen.getByText('Alex Admin')).toBeInTheDocument()
    expect(screen.getByText('Casey Collaborator')).toBeInTheDocument()
    expect(screen.getByText('Showing 2 of 2 team members.')).toBeInTheDocument()
  })

  it('filters and updates search query', () => {
    const props = defaultProps()
    render(<TeamMembersTab {...props} />)

    const searchInput = screen.getByPlaceholderText('Search by name or email')
    fireEvent.change(searchInput, { target: { value: 'casey' } })
    expect(props.onSearchChange).toHaveBeenCalledWith('casey')

    const statusSelect = screen.getByDisplayValue('All statuses')
    fireEvent.change(statusSelect, { target: { value: 'active' } })
    expect(props.onStatusFilterChange).toHaveBeenCalledWith('active')
  })

  it('allows admins to update roles and cookie actions', () => {
    const props = defaultProps()
    render(<TeamMembersTab {...props} />)

    const rows = screen.getAllByRole('row')
    expect(rows.length).toBeGreaterThan(1)
    const firstRow = rows[1] as HTMLElement

    const roleSelect = within(firstRow).getByDisplayValue('Admin')
    fireEvent.change(roleSelect, { target: { value: 'user' } })
    expect(props.onRoleChange).toHaveBeenCalledWith(1, 'user')

    const deactivateButton = within(firstRow).getByRole('button', { name: 'Deactivate' })
    fireEvent.click(deactivateButton)
    expect(props.onToggleStatus).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))

    const resetPasswordButton = within(firstRow).getByRole('button', { name: 'Reset Password' })
    fireEvent.click(resetPasswordButton)
    expect(props.onResetPassword).toHaveBeenCalledWith(1)
  })
})
