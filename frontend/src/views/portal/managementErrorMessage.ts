export function managementErrorMessage(error: unknown) {
  const err = error as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = err.response?.data?.detail
  if (Array.isArray(detail)) {
    const fieldMap: Record<string, string> = {
      username: '登录账号',
      password: '初始密码',
      display_name: '用户姓名',
      identities: '登录身份',
      role_code: '角色',
      identity_name: '身份名称',
      tenant_name: '企业名称',
      menu_ids: '菜单权限',
    }
    const translate = (msg: string) => {
      if (msg.includes('at least 3 characters')) return '至少填写 3 个字符'
      if (msg.includes('at least 2 characters')) return '至少填写 2 个字符'
      if (msg.includes('at least 6 characters')) return '至少填写 6 个字符'
      if (msg.includes('String should have at most')) return '内容过长'
      if (msg.includes('Field required')) return '不能为空'
      return msg
    }
    return detail.map((item: { loc?: string[]; msg?: string }) => {
      const field = String(item.loc?.slice(-1)[0] || '字段')
      return `${fieldMap[field] || field}：${translate(item.msg || '')}`
    }).join('；')
  }
  if (typeof detail === 'string') return detail
  return err.message || '操作失败，请稍后重试'
}
