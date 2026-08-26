import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { useAppContext } from '../../app/AppContext'
import { SettingsGroup, SettingsItem, SettingsSection, StatusBadge } from '../../components/settings'
import { actionToast, Button, Icons, LoadingState, PageFrame, StatusNotice } from '../../design-system'

const errorMessage = (caught: unknown, fallback: string) => caught instanceof ApiError
  ? caught.message
  : caught instanceof Error && caught.message
    ? caught.message
    : fallback

export function SettingsIgnoredPage() {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const ignored = useQuery({
    queryKey: queryKeys.ignored(user.id),
    queryFn: ({ signal }) => api.ignoredFeed(200, 0, signal),
    staleTime: queryStaleTime.collection,
  })
  const restoreMutation = useMutation({
    mutationFn: (articleId: string) => api.updateItemState(articleId, { dismissed: false }),
    onSuccess: async (_result, articleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.ignored(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }) }),
      ])
      const restored = ignored.data?.items.find((item) => item.id === articleId)
      actionToast.success('已恢复到信息流', { description: restored?.presentation?.content?.title || restored?.title })
    },
    onError: (caught) => actionToast.danger('恢复失败', { description: errorMessage(caught, '请稍后重试。') }),
  })

  return <div data-settings-page="ignored" data-page-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="已忽略内容" description="忽略后的信息只在这里恢复，不会继续占用日常浏览空间。">
        {ignored.isPending
          ? <LoadingState label="正在读取已忽略内容" rows={2} />
          : ignored.isError
            ? <StatusNotice title="已忽略内容读取失败" status="warning">
              <Button size="sm" variant="ghost" onPress={() => void ignored.refetch()}>重试此区域</Button>
            </StatusNotice>
            : <SettingsGroup ariaLabel="已忽略内容列表">
              {!ignored.data?.items.length
                ? <SettingsItem
                  label="暂无已忽略内容"
                  description="在信息流中忽略的内容会显示在这里，方便随时恢复。"
                  icon={<Icons.EyeOff size={17} aria-hidden="true" />}
                  trailing={<StatusBadge>0 条</StatusBadge>}
                />
                : ignored.data.items.map((item) => <SettingsItem
                  key={item.id}
                  label={item.presentation?.content?.title || item.title || '无标题内容'}
                  description={item.presentation?.source?.name || item.source || '未知来源'}
                  icon={<Icons.EyeOff size={17} aria-hidden="true" />}
                  trailing={<Button
                    size="sm"
                    variant="ghost"
                    isDisabled={restoreMutation.isPending && restoreMutation.variables === item.id}
                    onPress={() => restoreMutation.mutate(item.id)}
                  >{restoreMutation.isPending && restoreMutation.variables === item.id ? '恢复中…' : '恢复'}</Button>}
                />)}
            </SettingsGroup>}
      </SettingsSection>
    </PageFrame>
  </div>
}
