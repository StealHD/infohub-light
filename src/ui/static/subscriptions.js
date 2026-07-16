// Inteliscope static UI: subscription console module.
'use strict';

var FEED_SCHEDULE_WATCH_INTERVAL_MS = 30000;

function captureSubscriptionAction() {
  return {
    generation: Number(state.subscriptionActionGeneration || 0),
    userId: currentFeedScheduleWatchUserId(),
  };
}

function subscriptionActionIsCurrent(action) {
  return !!action &&
    Number(state.subscriptionActionGeneration || 0) === Number(action.generation || 0) &&
    currentFeedScheduleWatchUserId() === action.userId;
}

function invalidateSubscriptionActions() {
  state.subscriptionActionGeneration = Number(state.subscriptionActionGeneration || 0) + 1;
  state.subscriptionJobSubmission = false;
  var activePoll = state.subscriptionJobPoll;
  if (activePoll && activePoll.timer) window.clearTimeout(activePoll.timer);
  state.subscriptionJobPollGeneration = Number(state.subscriptionJobPollGeneration || 0) + 1;
  state.subscriptionJobPoll = null;
}

function subscriptionUserIsViewer() {
  return !!(state.auth.user && state.auth.user.role === 'viewer');
}

function subscriptionUserIsAdmin() {
  return !!(state.auth.user && ['owner', 'admin'].indexOf(state.auth.user.role) >= 0);
}

function viewerWriteDisabledAttr() {
  return subscriptionUserIsViewer() ? ' disabled title="viewer 只读，不能执行写操作" aria-disabled="true"' : '';
}

function jobControlMatches(control, jobType, sourceId, subscriptionId) {
  if (!control) return false;
  if (!jobType) return true;
  var controlJobType = control.jobType || control.job_type || '';
  var controlSourceId = control.sourceId || control.source_id || null;
  var controlSubscriptionId = control.subscriptionId || control.subscription_id || null;
  if (controlJobType !== jobType) return false;
  if (sourceId && controlSourceId !== sourceId) return false;
  if (subscriptionId && controlSubscriptionId && controlSubscriptionId !== subscriptionId) return false;
  return true;
}

function currentUserActiveSubscriptionJobs() {
  var jobs = (((state.subscriptionConsole || {}).jobs) || []).slice();
  var scheduledActive = state.feedSchedule && state.feedSchedule.active_job;
  if (scheduledActive && !jobs.some(function (job) { return job.id === scheduledActive.id; })) {
    jobs.push(scheduledActive);
  }
  var currentUserId = state.auth.user && state.auth.user.id;
  return jobs.filter(function (job) {
    var ownedByCurrentUser = !currentUserId || job.user_id === currentUserId;
    return ownedByCurrentUser && ['queued', 'running'].indexOf(job.status) >= 0;
  });
}

function subscriptionJobPending(jobType, sourceId, subscriptionId) {
  if (jobControlMatches(state.subscriptionJobSubmission, jobType, sourceId, subscriptionId) ||
      jobControlMatches(state.subscriptionJobPoll, jobType, sourceId, subscriptionId)) {
    return true;
  }
  return currentUserActiveSubscriptionJobs().some(function (job) {
    return jobControlMatches(job, jobType, sourceId, subscriptionId);
  });
}

function beginJobSubmission(jobType, sourceId, subscriptionId) {
  if (subscriptionUserIsViewer()) {
    updateFeedRefreshButtons();
    return false;
  }
  if (subscriptionJobPending(jobType, sourceId, subscriptionId)) return false;
  state.subscriptionJobSubmission = {
    jobType: jobType || '',
    sourceId: sourceId || null,
    subscriptionId: subscriptionId || null,
  };
  if (state.subscriptionConsole) renderSubscriptionConsole(state.subscriptionConsole);
  updateFeedRefreshButtons();
  return true;
}

function endJobSubmission() {
  state.subscriptionJobSubmission = false;
  if (state.subscriptionConsole) renderSubscriptionConsole(state.subscriptionConsole);
  updateFeedRefreshButtons();
}

function jobWriteDisabledAttr(jobType, sourceId, subscriptionId) {
  if (subscriptionUserIsViewer()) return viewerWriteDisabledAttr();
  return subscriptionJobPending(jobType, sourceId, subscriptionId)
    ? ' disabled title="任务执行中" aria-disabled="true"'
    : '';
}

function updateFeedRefreshButtons() {
  var viewer = subscriptionUserIsViewer();
  var pending = subscriptionJobPending('user_feed_refresh');
  var title = viewer ? 'viewer 只读，不能执行写操作' : (pending ? '任务执行中' : '');
  var headerButton = document.getElementById('refreshBtn');
  var subscriptionButton = document.getElementById('refreshMyFeedBtn');
  if (headerButton) {
    headerButton.disabled = viewer || pending;
    headerButton.title = title || '创建信息流获取任务';
    headerButton.textContent = pending ? '正在获取' : '获取新内容';
  }
  if (subscriptionButton) {
    subscriptionButton.disabled = viewer || pending;
    subscriptionButton.title = title;
  }
}

function setSubscriptionMessage(message, type) {
  var el = document.getElementById('subscriptionMessage');
  if (!el) return;
  el.textContent = message || '';
  el.className = 'config-message' + (type ? ' ' + type : '');
}

async function fetchSubscriptionApi(path, options) {
  var response = await fetch(path, options || {});
  var payload = await response.json();
  if (!response.ok) {
    if (response.status === 401 && typeof handleConfigUnauthorized === 'function') {
      await handleConfigUnauthorized(apiErrorMessage(payload, '登录已失效，请重新登录。'));
    }
    throw new Error(apiErrorMessage(payload, 'HTTP ' + response.status));
  }
  return unwrapApiPayload(payload);
}

function emptySourceHealthProjection() {
  return {
    schema_version: 1,
    scope: 'user',
    summary: { total: 0, healthy: 0, degraded: 0, failing: 0, unknown: 0 },
    items: [],
  };
}

function sourceHealthLoadIsCurrent(loadToken, userId, externalIsCurrent) {
  return state.sourceHealthLoadToken === loadToken &&
    state.sourceHealthLoadUserId === userId &&
    currentFeedScheduleWatchUserId() === userId &&
    (typeof externalIsCurrent !== 'function' || externalIsCurrent());
}

function invalidateSourceHealthLoads(clearData) {
  state.sourceHealthLoadToken = (state.sourceHealthLoadToken || 0) + 1;
  state.sourceHealthLoading = false;
  state.sourceHealthLoadUserId = null;
  state.sourceHealthLoadPromise = null;
  state.sourceHealthLoaded = false;
  state.sourceHealthSyncedJobIds = {};
  state.sourceHealthTerminalSyncPromises = {};
  if (clearData !== false) {
    state.sourceHealth = null;
    if (state.subscriptionConsole) {
      state.subscriptionConsole.sourceHealth = emptySourceHealthProjection();
    }
  }
}

async function loadSourceHealth(options) {
  options = options || {};
  var userId = currentFeedScheduleWatchUserId();
  var afterToken = Number(options.afterToken || 0);
  if (state.sourceHealthLoading &&
      state.sourceHealthLoadUserId === userId &&
      Number(state.sourceHealthLoadToken || 0) > afterToken &&
      state.sourceHealthLoadPromise) {
    var sharedResult = await state.sourceHealthLoadPromise;
    return currentFeedScheduleWatchUserId() === userId &&
      (typeof options.isCurrent !== 'function' || options.isCurrent())
      ? sharedResult
      : null;
  }

  if (state.sourceHealthLoadUserId !== userId) {
    state.sourceHealth = null;
    state.sourceHealthLoaded = false;
  }
  var loadToken = (state.sourceHealthLoadToken || 0) + 1;
  state.sourceHealthLoadToken = loadToken;
  state.sourceHealthLoadUserId = userId;
  state.sourceHealthLoading = true;
  var requestPromise = (async function () {
    try {
      var sourceHealth = await fetchSubscriptionApi('/api/me/source-health?ts=' + Date.now());
      if (!sourceHealthLoadIsCurrent(loadToken, userId, options.isCurrent)) return null;
      state.sourceHealth = sourceHealth || emptySourceHealthProjection();
      state.sourceHealthLoaded = true;
      if (state.subscriptionConsole) {
        state.subscriptionConsole.sourceHealth = state.sourceHealth;
        if (options.render !== false) renderSubscriptionConsole(state.subscriptionConsole);
      }
      return state.sourceHealth;
    } catch (err) {
      if (sourceHealthLoadIsCurrent(loadToken, userId, options.isCurrent) && !options.silent) {
        setSubscriptionMessage('来源健康读取失败：' + err.message, 'error');
      }
      return null;
    } finally {
      if (state.sourceHealthLoadToken === loadToken &&
          state.sourceHealthLoadUserId === userId) {
        state.sourceHealthLoading = false;
        state.sourceHealthLoadPromise = null;
      }
    }
  })();
  state.sourceHealthLoadPromise = requestPromise;
  return requestPromise;
}

function feedActivityLoadIsCurrent(loadToken, userId, externalIsCurrent) {
  return Number(state.feedActivityLoadToken || 0) === Number(loadToken || 0) &&
    state.feedActivityLoadUserId === userId &&
    currentFeedScheduleWatchUserId() === userId &&
    (typeof externalIsCurrent !== 'function' || externalIsCurrent());
}

function invalidateFeedActivityLoads(clearData) {
  state.feedActivityLoadToken = Number(state.feedActivityLoadToken || 0) + 1;
  state.feedActivityLoading = false;
  state.feedActivityLoadUserId = null;
  state.feedActivityLoaded = false;
  if (clearData !== false) state.feedActivity = null;
}

function feedActivitySnapshotJob() {
  var data = state.data || {};
  if (!data.snapshot_id && !data.run_id && !data.generated_at) return null;
  return {
    id: data.job_id || data.snapshot_id || data.run_id || 'latest-snapshot',
    user_id: currentFeedScheduleWatchUserId(),
    job_type: 'user_feed_refresh',
    status: data.run_status || 'succeeded',
    finished_at: data.generated_at || null,
    updated_at: data.generated_at || null,
    result_json: {
      snapshot_id: data.snapshot_id || null,
      item_count: data.item_count != null
        ? data.item_count
        : (((data.items || data.today_items) || []).length),
      source_outcomes: Array.isArray(data.source_outcomes) ? data.source_outcomes : [],
      issues: Array.isArray(data.issues) ? data.issues : [],
    },
  };
}

function latestCurrentUserRefreshJob(jobs, userId) {
  return (jobs || []).filter(function (job) {
    return job && job.job_type === 'user_feed_refresh' && job.user_id === userId;
  }).sort(function (left, right) {
    var leftTime = Date.parse(left.updated_at || left.created_at || '') || 0;
    var rightTime = Date.parse(right.updated_at || right.created_at || '') || 0;
    return rightTime - leftTime;
  })[0] || null;
}

function currentUserFeedScheduleRefreshJob(userId) {
  var schedule = state.feedSchedule || {};
  return [schedule.active_job, schedule.last_job].find(function (job) {
    return job &&
      job.job_type === 'user_feed_refresh' &&
      job.user_id === userId;
  }) || null;
}

async function loadFeedActivity(options) {
  options = options || {};
  var userId = currentFeedScheduleWatchUserId();
  var loadToken = Number(state.feedActivityLoadToken || 0) + 1;
  state.feedActivityLoadToken = loadToken;
  state.feedActivityLoadUserId = userId;
  state.feedActivityLoading = true;
  try {
    var data = await fetchSubscriptionApi('/api/jobs?limit=20&ts=' + Date.now());
    if (!feedActivityLoadIsCurrent(loadToken, userId, options.isCurrent)) return null;
    var job = currentUserFeedScheduleRefreshJob(userId) ||
      latestCurrentUserRefreshJob((data && data.jobs) || [], userId) ||
      feedActivitySnapshotJob();
    if (job && typeof setFeedActivity === 'function') {
      setFeedActivity(job, {
        workerStatus: (state.feedSchedule && state.feedSchedule.worker_status) || 'unknown',
      });
    } else {
      state.feedActivity = null;
      state.feedActivityLoaded = true;
      if (options.render !== false && typeof renderFeedActivityBanner === 'function') {
        renderFeedActivityBanner();
      }
    }
    return state.feedActivity;
  } catch (err) {
    if (feedActivityLoadIsCurrent(loadToken, userId, options.isCurrent) && !options.silent) {
      setSubscriptionMessage('刷新活动读取失败：' + err.message, 'error');
    }
    return null;
  } finally {
    if (feedActivityLoadIsCurrent(loadToken, userId, options.isCurrent)) {
      state.feedActivityLoading = false;
    }
  }
}

function feedScheduleSkipReason(reason) {
  return {
    active_user_feed_refresh: '已有信息流刷新任务，本周期未重复创建',
    user_disabled: '当前用户已停用',
    user_read_only: '当前用户为 viewer，只读计划已关闭',
    no_enabled_subscriptions: '没有有效订阅',
    quota_exceeded: '当日抓取配额已用尽',
    migration_required: '数据库需要完成 Feed v2 迁移',
    active_source_fetch: '来源抓取任务正在运行，计划已延后 5 分钟',
  }[reason] || reason || '';
}

function feedScheduleIssueSummary(job) {
  var result = (job && job.result_json) || {};
  var issues = Array.isArray(result.issues) ? result.issues : [];
  if (!issues.length) return '';
  var details = issues.slice(0, 2).map(function (issue) {
    return [issue && issue.code, issue && issue.message].filter(Boolean).join(': ');
  }).filter(Boolean).join('；');
  if (details.length > 180) details = details.slice(0, 177) + '...';
  return issues.length + ' 个问题/失败来源' + (details ? '：' + details : '');
}

function renderFeedScheduleCard(schedule) {
  schedule = schedule || {};
  var viewer = subscriptionUserIsViewer();
  var disabled = viewer ? ' disabled' : '';
  var enabled = schedule.enabled === true;
  var interval = Number(schedule.interval_minutes) || 360;
  var intervals = Array.isArray(schedule.allowed_intervals) && schedule.allowed_intervals.length
    ? schedule.allowed_intervals
    : [60, 180, 360, 720, 1440];
  var labels = { 60: '1 小时', 180: '3 小时', 360: '6 小时', 720: '12 小时', 1440: '24 小时' };
  var lastJob = schedule.last_job || {};
  var lastResult = lastJob.result_json || {};
  var activeJob = schedule.active_job || null;
  var workerStatus = schedule.worker_status || 'unknown';
  var issueSummary = feedScheduleIssueSummary(lastJob);
  var skipReason = feedScheduleSkipReason(schedule.last_skip_reason);
  var warning = '';
  if (workerStatus === 'missing' || workerStatus === 'stale') {
    warning = '<p class="feed-schedule-warning">Worker ' + escapeHtml(workerStatus) + '：自动任务暂时不会执行。</p>';
  }
  return [
    '<section class="subscription-section feed-schedule-section">',
    '  <div class="subscription-section-head"><h3>自动更新信息流</h3><span>' + (viewer ? 'viewer 只读' : '按用户独立设置') + '</span></div>',
    '  <div class="feed-schedule-card">',
    '    <form id="feedScheduleForm" class="feed-schedule-form">',
    '      <label class="feed-schedule-toggle"><input name="enabled" type="checkbox"' + (enabled ? ' checked' : '') + disabled + ' /><span>自动刷新</span></label>',
    '      <label class="field"><span>周期</span><select name="interval_minutes"' + disabled + '>' + intervals.map(function (value) {
      var numeric = Number(value);
      return '<option value="' + numeric + '"' + (numeric === interval ? ' selected' : '') + '>' + escapeHtml(labels[numeric] || (numeric + ' 分钟')) + '</option>';
    }).join('') + '</select></label>',
    '      <button type="submit"' + disabled + '>保存计划</button>',
    '    </form>',
    '    <div class="feed-schedule-status">',
    '      <div><span>上次自动刷新</span><strong>' + escapeHtml(formatDate(schedule.last_enqueued_at)) + '</strong></div>',
    '      <div><span>状态</span><strong>' + escapeHtml(lastJob.status || '尚未运行') + '</strong></div>',
    '      <div><span>产出</span><strong>' + escapeHtml(lastResult.item_count != null ? String(lastResult.item_count) + ' 条' : '未知') + '</strong></div>',
    '      <div><span>下次刷新</span><strong>' + escapeHtml(formatDate(schedule.next_run_at)) + '</strong></div>',
    '      <div><span>Worker</span><strong>Worker ' + escapeHtml(workerStatus) + '</strong></div>',
    '    </div>',
    activeJob ? '    <p class="feed-schedule-active">当前任务 ' + escapeHtml(activeJob.status || 'queued') + ' · ' + escapeHtml(activeJob.id || '') + '</p>' : '',
    issueSummary ? '    <p class="feed-schedule-warning">' + escapeHtml(issueSummary) + '</p>' : '',
    skipReason ? '    <p class="feed-schedule-note">最近跳过：' + escapeHtml(skipReason) + '</p>' : '',
    warning,
    '  </div>',
    '</section>',
  ].join('');
}

async function loadFeedSchedule(options) {
  options = options || {};
  if (state.feedScheduleLoading) {
    return typeof options.isCurrent === 'function' && !options.isCurrent()
      ? null
      : state.feedSchedule;
  }
  var loadToken = (state.feedScheduleLoadToken || 0) + 1;
  state.feedScheduleLoadToken = loadToken;
  state.feedScheduleLoading = true;
  try {
    var schedule = await fetchSubscriptionApi('/api/me/feed-schedule?ts=' + Date.now());
    if (typeof options.isCurrent === 'function' && !options.isCurrent()) return null;
    state.feedSchedule = schedule || {};
    state.feedScheduleLoaded = true;
    var activityJob = state.feedSchedule.active_job || state.feedSchedule.last_job;
    if (activityJob && typeof setFeedActivity === 'function') {
      setFeedActivity(activityJob, { workerStatus: state.feedSchedule.worker_status || 'unknown' });
    }
    if (state.subscriptionConsole) {
      state.subscriptionConsole.feedSchedule = state.feedSchedule;
      if (options.render !== false) renderSubscriptionConsole(state.subscriptionConsole);
    }
    if (options.resume !== false && state.feedSchedule.active_job) {
      resumeActiveFeedJobPoll([state.feedSchedule.active_job]);
    } else {
      updateFeedRefreshButtons();
    }
    return state.feedSchedule;
  } catch (err) {
    if (!options.silent) setSubscriptionMessage('自动刷新状态读取失败：' + err.message, 'error');
    return null;
  } finally {
    if (state.feedScheduleLoadToken === loadToken) state.feedScheduleLoading = false;
  }
}

function feedScheduleLastJobId(schedule) {
  return schedule && schedule.last_job && schedule.last_job.id
    ? schedule.last_job.id
    : null;
}

function feedTerminalJobHandled(jobId) {
  return !!(jobId && state.feedScheduleHandledJobIds && state.feedScheduleHandledJobIds[jobId]);
}

function markFeedTerminalJobHandled(jobId, updateScheduleObserved) {
  if (!jobId) return;
  state.feedScheduleHandledJobIds = state.feedScheduleHandledJobIds || {};
  state.feedScheduleHandledJobIds[jobId] = true;
  var ids = Object.keys(state.feedScheduleHandledJobIds);
  if (ids.length > 50) delete state.feedScheduleHandledJobIds[ids[0]];
  state.feedScheduleHandledJobId = jobId;
  if (updateScheduleObserved !== false) state.feedScheduleWatchLastJobId = jobId;
}

function sourceHealthTerminalJobSupported(job) {
  return !!job &&
    ['source_fetch', 'user_feed_refresh'].indexOf(job.job_type) >= 0 &&
    ['succeeded', 'partial', 'failed', 'cancelled'].indexOf(job.status) >= 0;
}

function sourceHealthTerminalJobSynced(jobId) {
  return !!(jobId && state.sourceHealthSyncedJobIds && state.sourceHealthSyncedJobIds[jobId]);
}

function markSourceHealthTerminalJobSynced(jobId) {
  if (!jobId) return;
  state.sourceHealthSyncedJobIds = state.sourceHealthSyncedJobIds || {};
  state.sourceHealthSyncedJobIds[jobId] = true;
  var ids = Object.keys(state.sourceHealthSyncedJobIds);
  if (ids.length > 50) delete state.sourceHealthSyncedJobIds[ids[0]];
}

async function refreshSourceHealthForTerminalJob(job, isCurrent) {
  if (!sourceHealthTerminalJobSupported(job)) return true;
  if (sourceHealthTerminalJobSynced(job.id)) return true;
  if (typeof isCurrent === 'function' && !isCurrent()) return false;
  state.sourceHealthTerminalSyncPromises = state.sourceHealthTerminalSyncPromises || {};
  if (state.sourceHealthTerminalSyncPromises[job.id]) {
    return state.sourceHealthTerminalSyncPromises[job.id];
  }
  var afterToken = Number(state.sourceHealthLoadToken || 0);
  var syncPromise = (async function () {
    var refreshed = await loadSourceHealth({
      silent: true,
      isCurrent: isCurrent,
      afterToken: afterToken,
    });
    if (!refreshed || (typeof isCurrent === 'function' && !isCurrent())) return false;
    markSourceHealthTerminalJobSynced(job.id);
    return true;
  })();
  state.sourceHealthTerminalSyncPromises[job.id] = syncPromise;
  try {
    return await syncPromise;
  } finally {
    if (state.sourceHealthTerminalSyncPromises[job.id] === syncPromise) {
      delete state.sourceHealthTerminalSyncPromises[job.id];
    }
  }
}

async function reloadFeedForTerminalJob(job, isCurrent, selectAll) {
  if (!job || !job.id) return false;
  if (feedTerminalJobHandled(job.id)) return true;
  if (state.feedScheduleReloadingJobId === job.id) return false;
  if (typeof isCurrent === 'function' && !isCurrent()) return false;
  state.feedScheduleReloadingJobId = job.id;
  var previousView = state.view;
  if (selectAll) state.view = 'all';
  try {
    var loaded = await loadData({ isCurrent: isCurrent });
    if (loaded !== true || (typeof isCurrent === 'function' && !isCurrent())) {
      if (selectAll && (typeof isCurrent !== 'function' || isCurrent())) state.view = previousView;
      return false;
    }
    markFeedTerminalJobHandled(job.id, job.job_type === 'user_feed_refresh');
    return true;
  } finally {
    if (state.feedScheduleReloadingJobId === job.id) {
      state.feedScheduleReloadingJobId = null;
    }
  }
}

function scheduleNextFeedScheduleWatch() {
  if (!state.feedScheduleWatcherStarted || state.feedScheduleWatchTimer) return;
  state.feedScheduleWatchTimer = window.setTimeout(function () {
    state.feedScheduleWatchTimer = null;
    return checkFeedScheduleUpdates();
  }, FEED_SCHEDULE_WATCH_INTERVAL_MS);
}

function currentFeedScheduleWatchUserId() {
  return state.auth.user && state.auth.user.id ? state.auth.user.id : null;
}

function feedScheduleWatchIsCurrent(generation, userId) {
  return state.feedScheduleWatcherStarted &&
    state.feedScheduleWatchGeneration === generation &&
    state.feedScheduleWatchUserId === userId &&
    currentFeedScheduleWatchUserId() === userId;
}

function startFeedScheduleWatcher() {
  if (!canUseConfig()) return;
  var userId = currentFeedScheduleWatchUserId();
  if (state.feedScheduleWatcherStarted && state.feedScheduleWatchUserId !== userId) {
    stopFeedScheduleWatcher();
  }
  if (!state.feedScheduleWatcherStarted) {
    state.feedScheduleWatchGeneration = (state.feedScheduleWatchGeneration || 0) + 1;
    state.feedScheduleWatcherStarted = true;
    state.feedScheduleWatchUserId = userId;
    state.feedScheduleWatchLastJobId = feedScheduleLastJobId(state.feedSchedule);
    state.feedScheduleHandledJobIds = {};
    state.feedScheduleHandledJobId = null;
    state.sourceHealthSyncedJobIds = {};
    var baselineLastJob = state.feedSchedule && state.feedSchedule.last_job;
    if (state.feedScheduleWatchLastJobId && sourceHealthTerminalJobSupported(baselineLastJob)) {
      markFeedTerminalJobHandled(state.feedScheduleWatchLastJobId);
      if (state.sourceHealthLoaded) {
        markSourceHealthTerminalJobSynced(state.feedScheduleWatchLastJobId);
      }
    }
  }
  scheduleNextFeedScheduleWatch();
}

function stopFeedScheduleWatcher() {
  state.feedScheduleWatchGeneration = (state.feedScheduleWatchGeneration || 0) + 1;
  state.feedScheduleWatcherStarted = false;
  state.feedScheduleWatchInFlight = false;
  if (state.feedScheduleWatchTimer) window.clearTimeout(state.feedScheduleWatchTimer);
  state.feedScheduleWatchTimer = null;
  state.feedScheduleWatchLastJobId = null;
  state.feedScheduleWatchUserId = null;
  state.feedScheduleHandledJobId = null;
  state.feedScheduleHandledJobIds = {};
  state.feedScheduleReloadingJobId = null;
  state.feedScheduleLoadToken = (state.feedScheduleLoadToken || 0) + 1;
  state.feedScheduleLoading = false;
  invalidateSourceHealthLoads(true);
  invalidateSubscriptionConsoleLoads(true);
  if (typeof invalidateFeedDataLoads === 'function') invalidateFeedDataLoads();
  cancelSubscriptionJobPoll();
}

async function checkFeedScheduleUpdates() {
  if (!state.feedScheduleWatcherStarted || state.feedScheduleWatchInFlight) return;
  if (!canUseConfig()) {
    stopFeedScheduleWatcher();
    return;
  }
  var generation = state.feedScheduleWatchGeneration;
  var userId = state.feedScheduleWatchUserId;
  state.feedScheduleWatchInFlight = true;
  try {
    var isCurrent = function () {
      return feedScheduleWatchIsCurrent(generation, userId);
    };
    var schedule = await loadFeedSchedule({ silent: true, isCurrent: isCurrent });
    if (!schedule || !isCurrent()) return;
    var lastJob = schedule.last_job || null;
    var lastJobId = feedScheduleLastJobId(schedule);
    var healthNeedsSync = sourceHealthTerminalJobSupported(lastJob) &&
      !sourceHealthTerminalJobSynced(lastJobId);
    if (lastJobId &&
        (lastJobId !== state.feedScheduleWatchLastJobId ||
         !feedTerminalJobHandled(lastJobId) ||
         healthNeedsSync)) {
      var result = lastJob.result_json || {};
      var activePollOwnsJob = state.subscriptionJobPoll &&
        state.subscriptionJobPoll.jobId === lastJobId;
      if (activePollOwnsJob) return;
      if (healthNeedsSync) {
        var healthSynced = await refreshSourceHealthForTerminalJob(lastJob, isCurrent);
        if (!healthSynced || !isCurrent()) return;
      }
      if (feedTerminalJobHandled(lastJobId)) {
        state.feedScheduleWatchLastJobId = lastJobId;
        return;
      }
      if (['succeeded', 'partial'].indexOf(lastJob.status) >= 0 && result.snapshot_id) {
        await reloadFeedForTerminalJob(lastJob, isCurrent, false);
      } else {
        markFeedTerminalJobHandled(lastJobId);
      }
    }
  } finally {
    state.feedScheduleWatchInFlight = false;
    scheduleNextFeedScheduleWatch();
  }
}

async function saveFeedSchedule(event) {
  event.preventDefault();
  if (subscriptionUserIsViewer()) return;
  var form = event.target.closest('form');
  if (!form) return;
  setSubscriptionMessage('正在保存自动刷新计划...', '');
  try {
    state.feedSchedule = await fetchSubscriptionApi('/api/me/feed-schedule', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: !!form.elements.enabled.checked,
        interval_minutes: Number(form.elements.interval_minutes.value) || 360,
      }),
    });
    state.feedScheduleLoaded = false;
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('自动刷新计划已更新。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('自动刷新计划更新失败：' + err.message, 'error');
  }
}

function subscriptionConsoleGenerationIsCurrent(loadToken, userId) {
  return Number(state.subscriptionConsoleLoadToken || 0) === Number(loadToken || 0) &&
    currentFeedScheduleWatchUserId() === userId;
}

function subscriptionConsoleLoadIsCurrent(loadToken, userId) {
  return subscriptionConsoleGenerationIsCurrent(loadToken, userId) &&
    state.subscriptionConsoleLoadUserId === userId;
}

function invalidateSubscriptionConsoleLoads(clearData) {
  state.subscriptionConsoleLoadToken = Number(state.subscriptionConsoleLoadToken || 0) + 1;
  state.subscriptionConsoleLoading = false;
  state.subscriptionConsoleLoadUserId = null;
  state.subscriptionConsoleLoaded = false;
  if (clearData !== false) state.subscriptionConsole = null;
}

async function loadSubscriptionConsole() {
  if (!canUseConfig()) {
    showLoginGate('请先登录后管理订阅。');
    return;
  }
  var loadUserId = currentFeedScheduleWatchUserId();
  if (state.subscriptionConsoleLoading && state.subscriptionConsoleLoadUserId === loadUserId) return;
  var loadToken = Number(state.subscriptionConsoleLoadToken || 0) + 1;
  state.subscriptionConsoleLoadToken = loadToken;
  state.subscriptionConsoleLoadUserId = loadUserId;
  state.subscriptionConsoleLoading = true;
  document.getElementById('subscriptionSummary').textContent = '正在读取订阅状态';
  document.getElementById('subscriptionConsole').innerHTML = '<div class="empty">正在读取订阅控制台...</div>';
  setSubscriptionMessage('', '');
  try {
    var admin = subscriptionUserIsAdmin();
    var requests = [
      fetchSubscriptionApi('/api/dashboard/summary?ts=' + Date.now()),
      fetchSubscriptionApi('/api/catalog/sources?ts=' + Date.now()),
      fetchSubscriptionApi('/api/catalog/source-types?ts=' + Date.now()),
      fetchSubscriptionApi('/api/me/subscriptions?ts=' + Date.now()),
      fetchSubscriptionApi('/api/jobs?ts=' + Date.now()),
      fetchSubscriptionApi('/api/feed/history?ts=' + Date.now()),
      fetchSubscriptionApi('/api/me/feed-schedule?ts=' + Date.now()),
      loadSourceHealth({ render: false }),
    ];
    if (admin) {
      requests.push(fetchSubscriptionApi('/api/users?ts=' + Date.now()));
      requests.push(fetchSubscriptionApi('/api/admin/secrets?ts=' + Date.now()));
    }
    var results = await Promise.all(requests);
    if (!subscriptionConsoleLoadIsCurrent(loadToken, loadUserId)) return;
    state.subscriptionConsole = {
      summary: results[0] || {},
      sources: (results[1] && results[1].sources) || [],
      sourceTypes: (results[2] && results[2].source_types) || [],
      subscriptions: (results[3] && results[3].subscriptions) || [],
      jobs: (results[4] && results[4].jobs) || [],
      feedSchedule: results[6] || {},
      sourceHealth: results[7] || state.sourceHealth || emptySourceHealthProjection(),
      members: admin ? ((results[8] && results[8].users) || []) : [],
      apiStatus: {
        history: results[5] || {},
      },
    };
    state.secrets = admin ? ((results[9] && results[9].secrets) || []) : [];
    state.feedSchedule = state.subscriptionConsole.feedSchedule;
    if (results[7]) state.sourceHealth = results[7];
    state.feedScheduleLoaded = true;
    state.subscriptionConsoleLoaded = true;
    renderSubscriptionConsole(state.subscriptionConsole);
    resumeActiveFeedJobPoll((state.feedSchedule.active_job ? [state.feedSchedule.active_job] : []).concat(state.subscriptionConsole.jobs));
  } catch (err) {
    if (!subscriptionConsoleLoadIsCurrent(loadToken, loadUserId)) return;
    document.getElementById('subscriptionConsole').innerHTML = '<div class="empty">订阅控制台读取失败。</div>';
    setSubscriptionMessage('读取失败：' + err.message, 'error');
  } finally {
    if (subscriptionConsoleLoadIsCurrent(loadToken, loadUserId)) {
      state.subscriptionConsoleLoading = false;
    }
  }
}

function sourceScopeLabel(scope) {
  return {
    public: '公共',
    workspace: '小组',
    private: '私有',
  }[scope] || scope || '未知';
}

function jobTypeLabel(type) {
  return {
    source_test: '测试源',
    source_fetch: '抓取源',
    user_feed_refresh: '刷新信息流',
  }[type] || type || '任务';
}

function jobIssueText(job) {
  var result = (job && job.result_json) || {};
  var issues = Array.isArray(result.issues) ? result.issues : [];
  return issues.map(function (issue) {
    if (!issue || typeof issue !== 'object') return '';
    return [issue.code, issue.message].filter(Boolean).join(': ');
  }).filter(Boolean).join('；');
}

function jobErrorText(job) {
  if (!job) return '';
  return [job.error_code, job.error_message].filter(Boolean).join(': ') || jobIssueText(job);
}

function subscriptionSourceMap(subscriptions) {
  var map = {};
  (subscriptions || []).forEach(function (subscription) {
    map[subscription.source_id] = subscription;
  });
  return map;
}

function sourceHealthItemMap(sourceHealth) {
  var map = {};
  (((sourceHealth || {}).items) || []).forEach(function (item) {
    if (item && item.subscription_id) map[item.subscription_id] = item;
  });
  return map;
}

function sourceHealthStatus(status) {
  return {
    healthy: { label: '正常', className: 'healthy' },
    degraded: { label: '需关注', className: 'degraded' },
    failing: { label: '连续失败', className: 'failing' },
    unknown: { label: '尚未抓取', className: 'unknown' },
  }[status] || { label: '尚未抓取', className: 'unknown' };
}

function shortSourceHealthMessage(value) {
  var message = String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
  return message.length > 160 ? message.slice(0, 157) + '...' : message;
}

function renderSourceHealthSummary(sourceHealth) {
  var summary = (sourceHealth && sourceHealth.summary) || {};
  var metrics = [
    ['', '总计', summary.total],
    ['healthy', '正常', summary.healthy],
    ['degraded', '需关注', summary.degraded],
    ['failing', '连续失败', summary.failing],
    ['unknown', '尚未抓取', summary.unknown],
  ];
  return [
    '<section class="subscription-section source-health-section">',
    '  <div class="subscription-section-head"><h3>来源健康</h3><span>按我的订阅统计</span></div>',
    '  <div class="source-health-summary">',
    metrics.map(function (metric) {
      var filter = metric[0];
      var value = metric[2] == null ? 0 : metric[2];
      var active = state.sourceHealthFilter === filter;
      return '<button type="button" data-source-health-filter="' + escapeHtml(filter) + '" class="' +
        (active ? 'active' : '') + '" aria-pressed="' + (active ? 'true' : 'false') + '"><span>' +
        escapeHtml(metric[1]) + '</span><strong>' + escapeHtml(String(value)) + '</strong></button>';
    }).join(''),
    '  </div>',
    '</section>',
  ].join('');
}

function sourceHealthFilterMatches(health, filter) {
  if (!filter) return true;
  var status = (health && health.status) || 'unknown';
  if (filter === 'attention') return status === 'degraded' || status === 'failing';
  return status === filter;
}

function setSourceHealthFilter(filter) {
  var allowed = ['', 'healthy', 'degraded', 'failing', 'unknown', 'attention'];
  state.sourceHealthFilter = allowed.indexOf(filter) >= 0 ? filter : '';
  if (state.subscriptionConsole) renderSubscriptionConsole(state.subscriptionConsole);
}

function renderSourceHealthDetails(health) {
  health = health || {
    status: 'unknown',
    last_attempt_at: null,
    last_success_at: null,
    last_fetched_count: 0,
    last_issue: null,
  };
  var status = sourceHealthStatus(health.status);
  var issue = health.last_issue && typeof health.last_issue === 'object'
    ? health.last_issue
    : null;
  var retryability = issue && Object.prototype.hasOwnProperty.call(issue, 'retryable')
    ? '<span class="source-health-retryability ' + (issue.retryable ? 'retryable' : 'non-retryable') + '">' +
      (issue.retryable ? '可重试' : '不可重试') + '</span>'
    : '';
  var issueLine = issue
    ? [
      '<div class="source-health-issue">',
      issue.code ? '<strong>' + escapeHtml(issue.code) + '</strong>' : '',
      issue.message ? '<span>' + escapeHtml(shortSourceHealthMessage(issue.message)) + '</span>' : '',
      retryability,
      '</div>',
    ].join('')
    : '';
  var fetchedCount = health.last_fetched_count == null ? 0 : health.last_fetched_count;
  return [
    '<div class="source-health-details">',
    '  <span class="source-health-badge ' + status.className + '">' + status.label + '</span>',
    '  <div class="source-health-diagnostics">',
    '    <div><span>上次尝试</span><strong>' + escapeHtml(formatDate(health.last_attempt_at)) + '</strong></div>',
    '    <div><span>上次成功</span><strong>' + escapeHtml(formatDate(health.last_success_at)) + '</strong></div>',
    '    <div><span>抓取条数</span><strong>' + escapeHtml(String(fetchedCount)) + ' 条</strong></div>',
    '  </div>',
    issueLine,
    '</div>',
  ].join('');
}

function topicText(topics) {
  return (topics || []).length ? topics.join('、') : '未设置主题';
}

function sourceTypeDefinition(sourceType, sourceTypes) {
  return (sourceTypes || []).find(function (definition) {
    return definition && definition.type === sourceType;
  }) || { type: sourceType, label: sourceType, fields: [], required_fields: [], template: {} };
}

function sourceTypeFields(definition) {
  definition = definition || {};
  if (Array.isArray(definition.fields) && definition.fields.length) {
    return definition.fields.filter(function (field) {
      return field && field.name;
    }).map(function (field) {
      return {
        name: String(field.name),
        label: field.label || field.name,
        input_type: field.input_type || 'text',
        required: field.required === true,
        default: Object.prototype.hasOwnProperty.call(field, 'default') ? field.default : null,
        options: Array.isArray(field.options) ? field.options : [],
        min: field.min,
        max: field.max,
        help: field.help || '',
      };
    });
  }
  var template = definition.template && typeof definition.template === 'object'
    ? definition.template
    : {};
  var required = Array.isArray(definition.required_fields) ? definition.required_fields : [];
  var names = Object.keys(template);
  required.forEach(function (name) {
    if (names.indexOf(name) < 0) names.push(name);
  });
  return names.map(function (name) {
    var value = template[name];
    var inputType = Array.isArray(value)
      ? 'list'
      : (typeof value === 'number' ? 'number' : (typeof value === 'boolean' ? 'checkbox' : 'text'));
    return {
      name: name,
      label: name,
      input_type: inputType,
      required: required.indexOf(name) >= 0,
      default: value,
      options: [],
      min: null,
      max: null,
      help: '',
    };
  });
}

function sourceCanEdit(source) {
  if (!source || subscriptionUserIsViewer()) return false;
  var user = state.auth.user || {};
  if (source.scope === 'private') return !!user.id && source.owner_user_id === user.id;
  return subscriptionUserIsAdmin();
}

function sourceFieldOption(option) {
  if (option && typeof option === 'object') {
    return {
      value: Object.prototype.hasOwnProperty.call(option, 'value') ? option.value : option.label,
      label: option.label || option.value,
    };
  }
  return { value: option, label: option };
}

function renderSourceConfigField(field, config, disabled) {
  var value = Object.prototype.hasOwnProperty.call(config || {}, field.name)
    ? config[field.name]
    : field.default;
  var name = 'config.' + field.name;
  var required = field.required ? ' required' : '';
  var disabledAttr = disabled ? ' disabled' : '';
  var help = field.help ? '<small>' + escapeHtml(field.help) + '</small>' : '';
  var control = '';
  if (field.input_type === 'select') {
    control = '<select name="' + escapeHtml(name) + '"' + required + disabledAttr + '>' + field.options.map(function (rawOption) {
      var option = sourceFieldOption(rawOption);
      return '<option value="' + escapeHtml(String(option.value == null ? '' : option.value)) + '"' +
        (String(option.value) === String(value) ? ' selected' : '') + '>' +
        escapeHtml(String(option.label == null ? '' : option.label)) + '</option>';
    }).join('') + '</select>';
  } else if (field.input_type === 'boolean' || field.input_type === 'checkbox') {
    control = '<input name="' + escapeHtml(name) + '" type="checkbox"' + (value ? ' checked' : '') + disabledAttr + ' />';
  } else if (field.input_type === 'textarea') {
    control = '<textarea name="' + escapeHtml(name) + '" rows="3"' + required + disabledAttr + '>' +
      escapeHtml(value == null ? '' : String(value)) + '</textarea>';
  } else {
    var inputType = field.input_type === 'number' || field.input_type === 'url'
      ? field.input_type
      : 'text';
    var displayValue = Array.isArray(value) ? value.join(', ') : (value == null ? '' : String(value));
    control = '<input name="' + escapeHtml(name) + '" type="' + inputType + '" value="' +
      escapeHtml(displayValue) + '"' + required +
      (field.min != null ? ' min="' + escapeHtml(String(field.min)) + '"' : '') +
      (field.max != null ? ' max="' + escapeHtml(String(field.max)) + '"' : '') + disabledAttr + ' />';
  }
  return '<label class="field"><span>' + escapeHtml(field.label) + '</span>' + control + help + '</label>';
}

function renderSourceEditor(source, sourceTypes, subscribed) {
  if (!sourceCanEdit(source)) return '';
  var definition = sourceTypeDefinition(source.type, sourceTypes);
  var fields = sourceTypeFields(definition);
  var config = source.config && typeof source.config === 'object' ? source.config : {};
  return [
    '<details class="source-editor">',
    '  <summary>编辑来源</summary>',
    '  <form data-source-editor="' + escapeHtml(source.id) + '" data-source-type="' + escapeHtml(source.type) + '" data-source-scope="' + escapeHtml(source.scope || '') + '" data-source-owner-id="' + escapeHtml(source.owner_user_id || '') + '" data-subscription-id="' + escapeHtml((subscribed && subscribed.id) || '') + '">',
    '    <label class="field"><span>来源类型</span><input name="source_type" value="' + escapeHtml(source.type) + '" disabled readonly /></label>',
    '    <label class="field"><span>显示名称</span><input name="display_name" type="text" value="' + escapeHtml(source.display_name || '') + '" /></label>',
    '    <label class="field"><span>说明</span><input name="description" type="text" value="' + escapeHtml(source.description || '') + '" /></label>',
    '    <label class="field"><span>默认频道</span><input name="default_channel" type="text" value="' + escapeHtml(source.default_channel || '') + '" /></label>',
    '    <label class="field"><span>默认主题（逗号分隔）</span><input name="default_topics" type="text" value="' + escapeHtml((source.default_topics || []).join(', ')) + '" /></label>',
    fields.map(function (field) { return renderSourceConfigField(field, config); }).join(''),
    source.type === 'apify_social'
      ? (subscriptionUserIsAdmin() && typeof fieldSecretSelect === 'function'
        ? fieldSecretSelect('secret_env', 'Apify Key', 'apify', 'apify', source.secret_env || '')
        : '<p class="subscription-muted">Apify Key ' + (source.secret_configured ? '已由管理员配置' : '尚未配置') + '。</p>')
      : '',
    '    <label class="source-editor-enabled"><input name="enabled" type="checkbox"' + (source.enabled === false ? '' : ' checked') + ' /><span>启用来源</span></label>',
    '    <details class="source-editor-advanced"><summary>高级 JSON</summary><textarea name="config_json" rows="7" spellcheck="false">' + escapeHtml(JSON.stringify(config, null, 2)) + '</textarea></details>',
    '    <div class="source-editor-actions">',
    '      <button type="submit" data-editor-action="save">保存</button>',
    '      <button type="submit" data-editor-action="test">测试连接</button>',
    '      <button type="submit" data-editor-action="refetch">保存并重新抓取</button>',
    '    </div>',
    '  </form>',
    '</details>',
  ].join('');
}

function renderSubscriptionEditor(subscription) {
  if (!subscription || subscriptionUserIsViewer()) return '';
  var schedule = subscription.schedule || {};
  var scheduleEnabled = schedule.enabled === true;
  var scheduleInterval = Number(schedule.interval_minutes) || 60;
  var scheduleIntervals = Array.isArray(schedule.allowed_intervals) && schedule.allowed_intervals.length
    ? schedule.allowed_intervals
    : [30, 60, 180, 360, 720, 1440];
  return [
    '<details class="subscription-editor">',
    '  <summary>编辑订阅</summary>',
    '  <form data-subscription-editor="' + escapeHtml(subscription.id) + '" data-source-id="' + escapeHtml(subscription.source_id) + '">',
    '    <label class="field"><span>覆盖频道</span><input name="override_channel" type="text" value="' + escapeHtml(subscription.override_channel || '') + '" /></label>',
    '    <label class="field"><span>覆盖主题（逗号分隔）</span><input name="override_topics" type="text" value="' + escapeHtml((subscription.override_topics || []).join(', ')) + '" /></label>',
    '    <label class="field"><span>个人标签（逗号分隔）</span><input name="personal_tags" type="text" value="' + escapeHtml((subscription.personal_tags || []).join(', ')) + '" /></label>',
    '    <label class="field"><span>分析模式</span><select name="analysis_mode">',
    '      <option value="full"' + (subscription.analysis_mode === 'personal_only' ? '' : ' selected') + '>完整分析</option>',
    '      <option value="personal_only"' + (subscription.analysis_mode === 'personal_only' ? ' selected' : '') + '>仅个人规则（跳过 AI）</option>',
    '    </select></label>',
    '    <label class="field"><span>优先级</span><input name="priority" type="number" min="0" max="100" value="' + escapeHtml(String(subscription.priority || 0)) + '" /></label>',
    '    <label class="subscription-editor-enabled"><input name="enabled" type="checkbox"' + (subscription.enabled === false ? '' : ' checked') + ' /><span>启用订阅</span></label>',
    '    <fieldset class="source-schedule-editor">',
    '      <legend>单来源自动抓取</legend>',
    '      <label class="subscription-editor-enabled"><input name="source_schedule_enabled" type="checkbox"' + (scheduleEnabled ? ' checked' : '') + ' /><span>自动抓取此来源</span></label>',
    '      <label class="field"><span>周期</span><select name="source_schedule_interval_minutes">' + scheduleIntervals.map(function (value) {
      var numeric = Number(value);
      var label = numeric === 30 ? '30 分钟' : (numeric < 60 ? numeric + ' 分钟' : (numeric / 60) + ' 小时');
      return '<option value="' + numeric + '"' + (numeric === scheduleInterval ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
    }).join('') + '</select></label>',
    '      <p class="subscription-muted">仅抓取当前来源；不会触发其他订阅。</p>',
    '    </fieldset>',
    '    <div class="source-editor-actions">',
    '      <button type="submit" data-editor-action="save">保存</button>',
    '      <button type="submit" data-editor-action="test">测试连接</button>',
    '      <button type="submit" data-editor-action="refetch">保存并重新抓取</button>',
    '    </div>',
    '  </form>',
    '</details>',
  ].join('');
}

function editorList(value) {
  return String(value || '').split(',').map(function (item) { return item.trim(); }).filter(Boolean);
}

function sourceEditorPayload(form, definition) {
  var config = {};
  try {
    config = JSON.parse((form.elements.config_json && form.elements.config_json.value) || '{}');
  } catch (err) {
    throw new Error('高级 JSON 解析失败：' + err.message);
  }
  if (!config || typeof config !== 'object' || Array.isArray(config)) config = {};
  sourceTypeFields(definition).forEach(function (field) {
    var input = form.elements['config.' + field.name];
    if (!input) return;
    if (field.input_type === 'boolean' || field.input_type === 'checkbox') {
      config[field.name] = !!input.checked;
      return;
    }
    if (field.input_type === 'list') {
      config[field.name] = editorList(input.value);
      return;
    }
    if (field.input_type === 'number') {
      config[field.name] = String(input.value || '').trim() === '' ? null : Number(input.value);
      return;
    }
    var value = String(input.value || '').trim();
    config[field.name] = value || (field.required ? '' : null);
  });
  var payload = {
    display_name: String((form.elements.display_name && form.elements.display_name.value) || '').trim() || null,
    description: String((form.elements.description && form.elements.description.value) || '').trim() || null,
    default_channel: String((form.elements.default_channel && form.elements.default_channel.value) || '').trim() || null,
    default_topics: editorList(form.elements.default_topics && form.elements.default_topics.value),
    config: config,
    enabled: !!(form.elements.enabled && form.elements.enabled.checked),
  };
  if (form.elements.secret_env) {
    payload.secret_env = String(form.elements.secret_env.value || '').trim() || null;
  }
  return payload;
}

function subscriptionEditorPayload(form) {
  return {
    override_channel: String((form.elements.override_channel && form.elements.override_channel.value) || '').trim() || null,
    override_topics: editorList(form.elements.override_topics && form.elements.override_topics.value),
    personal_tags: editorList(form.elements.personal_tags && form.elements.personal_tags.value),
    analysis_mode: String((form.elements.analysis_mode && form.elements.analysis_mode.value) || 'full'),
    priority: Math.max(0, Math.min(100, Number((form.elements.priority && form.elements.priority.value) || 0))),
    enabled: !!(form.elements.enabled && form.elements.enabled.checked),
  };
}

function subscriptionSchedulePayload(form) {
  if (!form || !form.elements.source_schedule_enabled || !form.elements.source_schedule_interval_minutes) {
    return null;
  }
  return {
    enabled: !!(form.elements.enabled && form.elements.enabled.checked) &&
      !!form.elements.source_schedule_enabled.checked,
    interval_minutes: Number(form.elements.source_schedule_interval_minutes.value) || 60,
  };
}

function editorAction(event) {
  var submitter = event && event.submitter;
  return (submitter && submitter.getAttribute('data-editor-action')) || 'save';
}

async function saveSourceEditor(form, action, definition) {
  if (!form || subscriptionUserIsViewer()) return false;
  var actionContext = captureSubscriptionAction();
  var scope = form.getAttribute('data-source-scope');
  var ownerId = form.getAttribute('data-source-owner-id');
  if (scope && !sourceCanEdit({ scope: scope, owner_user_id: ownerId })) return false;
  var sourceId = form.getAttribute('data-source-editor');
  var sourceType = form.getAttribute('data-source-type');
  var subscriptionId = form.getAttribute('data-subscription-id') || null;
  definition = definition || sourceTypeDefinition(
    sourceType,
    ((state.subscriptionConsole || {}).sourceTypes) || []
  );
  var payload;
  try {
    payload = sourceEditorPayload(form, definition);
  } catch (err) {
    setSubscriptionMessage(err.message, 'error');
    return false;
  }
  setSubscriptionMessage('正在保存来源...', '');
  try {
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(sourceId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!subscriptionActionIsCurrent(actionContext)) return false;
    if (action === 'test') await queueSourceJob(sourceId, 'source_test', subscriptionId);
    if (action === 'refetch') await queueSourceJob(sourceId, 'source_fetch', subscriptionId);
    if (!subscriptionActionIsCurrent(actionContext)) return false;
    state.subscriptionConsoleLoaded = false;
    if (action === 'save') setSubscriptionMessage('来源已保存。', '');
    await loadSubscriptionConsole();
    if (!subscriptionActionIsCurrent(actionContext)) return false;
    return true;
  } catch (err) {
    if (subscriptionActionIsCurrent(actionContext)) {
      setSubscriptionMessage('来源保存失败：' + err.message, 'error');
    }
    return false;
  }
}

async function saveSubscriptionEditor(form, action) {
  if (!form || subscriptionUserIsViewer()) return false;
  var actionContext = captureSubscriptionAction();
  var subscriptionId = form.getAttribute('data-subscription-editor');
  var sourceId = form.getAttribute('data-source-id');
  var payload = subscriptionEditorPayload(form);
  var schedulePayload = subscriptionSchedulePayload(form);
  setSubscriptionMessage('正在保存订阅...', '');
  try {
    await fetchSubscriptionApi('/api/me/subscriptions/' + encodeURIComponent(subscriptionId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!subscriptionActionIsCurrent(actionContext)) return false;
    if (schedulePayload) {
      await fetchSubscriptionApi('/api/me/subscriptions/' + encodeURIComponent(subscriptionId) + '/schedule', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(schedulePayload),
      });
      if (!subscriptionActionIsCurrent(actionContext)) return false;
    }
    if (action === 'test') await queueSourceJob(sourceId, 'source_test', subscriptionId);
    if (action === 'refetch') await queueSourceJob(sourceId, 'source_fetch', subscriptionId);
    if (!subscriptionActionIsCurrent(actionContext)) return false;
    state.subscriptionConsoleLoaded = false;
    if (action === 'save') setSubscriptionMessage('订阅已保存。', '');
    await loadSubscriptionConsole();
    if (!subscriptionActionIsCurrent(actionContext)) return false;
    return true;
  } catch (err) {
    if (subscriptionActionIsCurrent(actionContext)) {
      setSubscriptionMessage('订阅保存失败：' + err.message, 'error');
    }
    return false;
  }
}

function renderSourceCard(source, subscribed, sourceTypes) {
  var subscriptionId = subscribed && subscribed.id ? subscribed.id : '';
  var viewerDisabledAttr = viewerWriteDisabledAttr();
  var testDisabledAttr = jobWriteDisabledAttr('source_test', source.id, subscriptionId);
  var fetchDisabledAttr = jobWriteDisabledAttr('source_fetch', source.id, subscriptionId);
  var subscriptionDataAttr = subscriptionId
    ? ' data-subscription-id="' + escapeHtml(subscriptionId) + '"'
    : '';
  var scope = source.scope || '';
  var secretLine = source.secret_configured
    ? '<span class="subscription-badge">管理员已配置 Key</span>'
    : '';
  var action = subscribed
    ? '<button type="button" data-unsubscribe-source="' + escapeHtml(source.id) + '"' + viewerDisabledAttr + '>取消订阅</button>'
    : '<button class="primary" type="button" data-subscribe-source="' + escapeHtml(source.id) + '"' + viewerDisabledAttr + '>订阅</button>';
  return [
    '<article class="subscription-card">',
    '  <div class="subscription-card-head">',
    '    <div>',
    '      <h4>' + escapeHtml(source.display_name || source.type || '未命名源') + '</h4>',
    '      <div class="subscription-meta">',
    '        <span>' + escapeHtml(source.type || 'source') + '</span>',
    '        <span>' + escapeHtml(source.default_channel || '未设置频道') + '</span>',
    '      </div>',
    '    </div>',
    '    <span class="subscription-badge ' + escapeHtml(scope) + '">' + escapeHtml(sourceScopeLabel(scope)) + '</span>',
    '  </div>',
    source.description ? '<p class="subscription-muted">' + escapeHtml(source.description) + '</p>' : '',
    '  <div class="subscription-meta">',
    '    <span class="subscription-badge">' + escapeHtml(topicText(source.default_topics)) + '</span>',
    secretLine,
    subscribed ? '<span class="subscription-badge">已订阅</span>' : '',
    '  </div>',
    '  <div class="subscription-card-actions">',
    action,
    '    <button type="button" data-source-test="' + escapeHtml(source.id) + '"' + subscriptionDataAttr + testDisabledAttr + '>测试</button>',
    '    <button type="button" data-source-fetch="' + escapeHtml(source.id) + '"' + subscriptionDataAttr + fetchDisabledAttr + '>抓取</button>',
    '  </div>',
    renderSourceEditor(source, sourceTypes, subscribed),
    '</article>',
  ].join('');
}

function renderSubscriptionCard(subscription, health) {
  var viewer = subscriptionUserIsViewer();
  var disabledAttr = viewerWriteDisabledAttr();
  var enabled = subscription.enabled !== false;
  var fetchDisabledAttr = jobWriteDisabledAttr(
    'source_fetch',
    subscription.source_id,
    subscription.id
  );
  var testDisabledAttr = jobWriteDisabledAttr(
    'source_test',
    subscription.source_id,
    subscription.id
  );
  return [
    '<article class="subscription-card">',
    '  <div class="subscription-card-head">',
    '    <div>',
    '      <h4>' + escapeHtml(subscription.source_display_name || subscription.source_id || '订阅源') + '</h4>',
    '      <div class="subscription-meta">',
    '        <span>' + escapeHtml(subscription.source_type || 'source') + '</span>',
    '        <span>' + escapeHtml(subscription.override_channel || '使用源默认频道') + '</span>',
    '      </div>',
    '    </div>',
    '    <span class="subscription-badge ' + (enabled ? '' : 'disabled') + '">' + (enabled ? '启用' : '停用') + '</span>',
    '  </div>',
    '  <div class="subscription-meta">',
    '    <span class="subscription-badge">' + escapeHtml(topicText(subscription.override_topics)) + '</span>',
    '    <span class="subscription-badge">' + escapeHtml(subscription.analysis_mode || 'full') + '</span>',
  '    <span class="subscription-badge">优先级 ' + escapeHtml(String(subscription.priority || 0)) + '</span>',
  '  </div>',
    renderSourceHealthDetails(health),
    renderSubscriptionEditor(subscription),
  '  <div class="subscription-card-actions">',
    '    <button type="button" data-toggle-subscription="' + escapeHtml(subscription.id) + '" data-enabled="' + (enabled ? '0' : '1') + '"' + disabledAttr + '>' + (enabled ? '停用' : '启用') + '</button>',
    '    <button type="button" data-unsubscribe-source="' + escapeHtml(subscription.source_id) + '"' + disabledAttr + '>取消订阅</button>',
    '    <button type="button" data-source-test="' + escapeHtml(subscription.source_id) + '" data-subscription-id="' + escapeHtml(subscription.id) + '"' + testDisabledAttr + '>测试连接</button>',
    '    <button type="button" data-source-fetch="' + escapeHtml(subscription.source_id) + '" data-subscription-id="' + escapeHtml(subscription.id) + '"' + fetchDisabledAttr + '>重新抓取</button>',
    health && health.last_job_id ? '    <button type="button" data-health-job="' + escapeHtml(health.last_job_id) + '">最近任务</button>' : '',
  '  </div>',
    '</article>',
  ].join('');
}

function privateSourceTopicOptions() {
  var tags = [];
  if (typeof getConfigTagLibrary === 'function') {
    tags = getConfigTagLibrary();
  }
  if (!tags.length && state.config && Array.isArray(state.config.tags)) {
    tags = state.config.tags;
  }
  if (!tags.length) tags = TAG_LIBRARY_OPTIONS;
  return tags.slice(0, 18);
}

function renderPrivateSourceForm() {
  var viewer = subscriptionUserIsViewer();
  var channelOptions = HUB_CHANNEL_OPTIONS.map(function (channel) {
    return '<option value="' + escapeHtml(channel) + '">' + escapeHtml(channel) + '</option>';
  }).join('');
  var topicOptions = privateSourceTopicOptions().map(function (topic) {
    return [
      '<label>',
      '  <input type="checkbox" name="default_topics" value="' + escapeHtml(topic) + '"' + (viewer ? ' disabled' : '') + ' />',
      '  <span>' + escapeHtml(topic) + '</span>',
      '</label>',
    ].join('');
  }).join('');
  return [
    '<form id="privateSourceForm" class="private-source-form">',
    '  <label class="field"><span>名称</span><input name="display_name" type="text" placeholder="我的 RSS 源" required' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field"><span>RSS URL</span><input name="feed_url" type="url" placeholder="https://example.com/feed.xml" required' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field"><span>Hub 频道</span><select name="default_channel"' + (viewer ? ' disabled' : '') + '>' + channelOptions + '</select></label>',
    '  <div class="subscription-topic-list" aria-label="阅读主题">' + topicOptions + '</div>',
    '  <div class="form-actions"><button type="submit"' + (viewer ? ' disabled' : '') + '>创建并订阅</button></div>',
    '</form>',
  ].join('');
}

function renderAdvancedSourceForm(sourceTypes) {
  var viewer = subscriptionUserIsViewer();
  var types = sourceTypes && sourceTypes.length ? sourceTypes : [
    { type: 'github_release', label: 'GitHub Releases', template: { owner: 'openai', repo: 'codex' } },
  ];
  var first = types[0] || {};
  var typeOptions = types.map(function (sourceType) {
    return '<option value="' + escapeHtml(sourceType.type) + '">' + escapeHtml(sourceType.label || sourceType.type) + '</option>';
  }).join('');
  var channelOptions = HUB_CHANNEL_OPTIONS.map(function (channel) {
    return '<option value="' + escapeHtml(channel) + '">' + escapeHtml(channel) + '</option>';
  }).join('');
  var initialConfig = first.template || {};
  var template = JSON.stringify(initialConfig, null, 2);
  var dynamicFields = sourceTypeFields(first).map(function (field) {
    return renderSourceConfigField(field, initialConfig, viewer);
  }).join('');
  return [
    '<form id="advancedSourceForm" class="advanced-source-form">',
    '  <label class="field"><span>source_type</span><select name="source_type"' + (viewer ? ' disabled' : '') + '>' + typeOptions + '</select></label>',
    '  <label class="field"><span>显示名称</span><input name="display_name" type="text" placeholder="高级源名称"' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <label class="field"><span>Hub 频道</span><select name="default_channel"' + (viewer ? ' disabled' : '') + '><option value="">不设置</option>' + channelOptions + '</select></label>',
    '  <div data-advanced-source-secret>' + renderAdvancedSourceSecret(first.type || '') + '</div>',
    '  <div class="advanced-source-dynamic wide" data-advanced-source-fields="' + escapeHtml(first.type || '') + '">' + dynamicFields + '</div>',
    '  <details class="source-editor-advanced wide"><summary>高级 JSON</summary><textarea name="config_json" rows="8" spellcheck="false"' + (viewer ? ' disabled' : '') + '>' + escapeHtml(template) + '</textarea></details>',
    '  <label class="field wide"><span>默认主题（逗号分隔）</span><input name="default_topics" type="text" placeholder="AI Agent, 产品机会"' + (viewer ? ' disabled' : '') + ' /></label>',
    '  <div class="form-actions"><button type="submit"' + (viewer ? ' disabled' : '') + '>创建并订阅</button></div>',
    '</form>',
  ].join('');
}

function renderAdvancedSourceSecret(sourceType) {
  if (sourceType !== 'apify_social') return '';
  if (!subscriptionUserIsAdmin() || typeof fieldSecretSelect !== 'function') {
    return '<p class="subscription-muted">Apify Key 由管理员配置。</p>';
  }
  return fieldSecretSelect('secret_env', 'Apify Key', 'apify', 'apify', '');
}

function updateAdvancedSourceFields(form, type) {
  if (!form) return;
  var definition = sourceTypeDefinition(type, ((state.subscriptionConsole || {}).sourceTypes) || []);
  var template = definition.template || {};
  var fields = form.querySelector('[data-advanced-source-fields]');
  if (fields) {
    fields.setAttribute('data-advanced-source-fields', type);
    fields.innerHTML = sourceTypeFields(definition).map(function (field) {
      return renderSourceConfigField(field, template, subscriptionUserIsViewer());
    }).join('');
  }
  var secretField = form.querySelector('[data-advanced-source-secret]');
  if (secretField) secretField.innerHTML = renderAdvancedSourceSecret(type);
  if (form.elements.config_json) form.elements.config_json.value = JSON.stringify(template, null, 2);
}

function renderSourceTestResult(job) {
  if (!job || job.job_type !== 'source_test' || job.status !== 'succeeded') return '';
  var result = job.result_json || {};
  var count = result.count == null ? null : Number(result.count);
  var sampleTitle = result.sample_title ? escapeHtml(shortSourceHealthMessage(result.sample_title)) : '';
  var sampleUrl = typeof safeExternalUrl === 'function' ? safeExternalUrl(result.sample_url) : '';
  var sample = sampleTitle;
  if (sampleUrl) {
    sample = '<a href="' + escapeHtml(sampleUrl) + '" target="_blank" rel="noopener noreferrer">' +
      (sampleTitle || '打开样例') + '</a>';
  }
  return [
    '<div class="source-test-result">',
    count != null && Number.isFinite(count) ? '<strong>预览 ' + escapeHtml(String(count)) + ' 条</strong>' : '',
    sample ? '<span>' + sample + '</span>' : '',
    result.message ? '<span>' + escapeHtml(shortSourceHealthMessage(result.message)) + '</span>' : '',
    '</div>',
  ].join('');
}

function renderJobs(jobs) {
  var visibleJobs = (jobs || []).slice(0, 8);
  if (!visibleJobs.length) return '<div class="empty">暂无任务。</div>';
  return [
    '<div class="subscription-job-list">',
    visibleJobs.map(function (job) {
      var canCancel = job.status === 'queued' && !subscriptionUserIsViewer();
      var canRetry = ['failed', 'partial', 'cancelled'].indexOf(job.status) >= 0 && !subscriptionUserIsViewer();
      var errorText = jobErrorText(job);
      return [
        '<div class="subscription-job-row" data-job-id="' + escapeHtml(job.id || '') + '">',
        '  <strong>' + escapeHtml(job.id || '') + '</strong>',
        '  <span>' + escapeHtml(jobTypeLabel(job.job_type)) + '</span>',
        '  <span>' + escapeHtml(job.status || '') + '</span>',
        '  <span>' + escapeHtml(String(job.attempts || 0)) + ' / ' + escapeHtml(String(job.max_attempts || 1)) + '</span>',
        '  <span>' + escapeHtml(formatDate(job.updated_at || job.created_at)) + '</span>',
        errorText ? '  <span class="subscription-job-error">' + escapeHtml(errorText) + '</span>' : '',
        renderSourceTestResult(job),
        '  <div class="subscription-job-actions">',
        canCancel ? '    <button type="button" data-cancel-job="' + escapeHtml(job.id) + '">取消</button>' : '',
        canRetry ? '    <button type="button" data-retry-job="' + escapeHtml(job.id) + '">重试</button>' : '',
        '  </div>',
        '</div>',
      ].join('');
    }).join(''),
    '</div>',
  ].join('');
}

function renderApiStatus(apiStatus, summary) {
  apiStatus = apiStatus || {};
  summary = summary || {};
  var snapshots = (apiStatus.history && apiStatus.history.snapshots) || [];
  var latest = snapshots[0] || {};
  var itemStateCounts = summary.item_state_counts || {};
  var runtime = summary.runtime || {};
  var workerStatus = runtime.worker_status || 'unknown';
  return [
    '<div class="subscription-api-status">',
    '  <div class="subscription-api-metrics">',
    '    <div><span>最新 snapshot</span><strong>' + escapeHtml(formatDate(latest.generated_at || summary.latest_generated_at || '')) + '</strong></div>',
    '    <div><span>可见 item</span><strong>' + escapeHtml(String(latest.item_count != null ? latest.item_count : 0)) + '</strong></div>',
    '    <div><span>失败任务</span><strong>' + escapeHtml(String(summary.failed_job_count || 0)) + '</strong></div>',
    '    <div><span>已读</span><strong>' + escapeHtml(String(itemStateCounts.read_count || 0)) + '</strong></div>',
    '    <div><span>收藏</span><strong>' + escapeHtml(String(itemStateCounts.saved_count || 0)) + '</strong></div>',
    '    <div><span>稍后读</span><strong>' + escapeHtml(String(itemStateCounts.later_count || 0)) + '</strong></div>',
    '    <div><span>已忽略</span><strong>' + escapeHtml(String(itemStateCounts.dismissed_count || 0)) + '</strong></div>',
    '    <div><span>Worker</span><strong>' + escapeHtml(workerStatus) + '</strong></div>',
    '  </div>',
    '</div>',
  ].join('');
}

function memberRoleOptions(selectedRole) {
  return ['owner', 'admin', 'member', 'viewer'].map(function (role) {
    return '<option value="' + role + '"' + (role === selectedRole ? ' selected' : '') + '>' + role + '</option>';
  }).join('');
}

function renderMemberManagement(members) {
  if (!subscriptionUserIsAdmin()) return '';
  members = members || [];
  var createRoleOptions = memberRoleOptions('member');
  var rows = members.map(function (member) {
    var enabled = member.enabled !== false;
    return [
      '<form class="member-edit-form" data-member-update="' + escapeHtml(member.id) + '">',
      '  <div class="member-identity">',
      '    <strong>' + escapeHtml(member.username || 'member') + '</strong>',
      '    <span>' + escapeHtml(member.id || '') + '</span>',
      '  </div>',
      '  <label class="field"><span>显示名</span><input name="display_name" type="text" value="' + escapeHtml(member.display_name || '') + '" /></label>',
      '  <label class="field"><span>角色</span><select name="role">' + memberRoleOptions(member.role || 'member') + '</select></label>',
      '  <label class="field member-enabled"><span>启用</span><input name="enabled" type="checkbox"' + (enabled ? ' checked' : '') + ' /></label>',
      '  <label class="field"><span>重置密码</span><input name="password" type="password" placeholder="留空不重置" autocomplete="new-password" /></label>',
      '  <div class="form-actions"><button type="submit">保存</button></div>',
      '</form>',
    ].join('');
  }).join('');
  return [
    '<section class="subscription-section member-management">',
    '  <div class="subscription-section-head"><h3>成员管理</h3><span>仅 owner/admin 可见</span></div>',
    '  <form id="memberManagementForm" class="member-management-form">',
    '    <label class="field"><span>用户名</span><input name="username" type="text" autocomplete="username" required /></label>',
    '    <label class="field"><span>初始密码</span><input name="password" type="password" autocomplete="new-password" required /></label>',
    '    <label class="field"><span>显示名</span><input name="display_name" type="text" /></label>',
    '    <label class="field"><span>角色</span><select name="role">' + createRoleOptions + '</select></label>',
    '    <label class="field member-enabled"><span>启用</span><input name="enabled" type="checkbox" checked /></label>',
    '    <div class="form-actions"><button type="submit">创建成员</button></div>',
    '  </form>',
    members.length ? '<div class="member-list">' + rows + '</div>' : '<div class="empty">还没有成员。</div>',
    '</section>',
  ].join('');
}

function renderSubscriptionConsole(data) {
  data = data || {};
  var summary = data.summary || {};
  var sources = data.sources || [];
  var subscriptions = data.subscriptions || [];
  var jobs = data.jobs || [];
  var members = data.members || [];
  var apiStatus = data.apiStatus || {};
  var feedSchedule = data.feedSchedule || state.feedSchedule || {};
  var sourceHealth = data.sourceHealth || state.sourceHealth || emptySourceHealthProjection();
  var sourceTypes = data.sourceTypes || [];
  var subscribedBySource = subscriptionSourceMap(subscriptions);
  var healthBySubscription = sourceHealthItemMap(sourceHealth);
  var visibleSubscriptions = subscriptions.filter(function (subscription) {
    return sourceHealthFilterMatches(
      healthBySubscription[subscription.id],
      state.sourceHealthFilter || ''
    );
  });
  var user = summary.current_user || state.auth.user || {};
  var viewer = subscriptionUserIsViewer();
  var admin = subscriptionUserIsAdmin();
  document.getElementById('subscriptionSummary').textContent = [
    user.username || state.auth.username || '当前用户',
    user.role || '',
    '可见源 ' + (summary.source_count != null ? summary.source_count : sources.length),
    '我的订阅 ' + (summary.subscription_count != null ? summary.subscription_count : subscriptions.length),
    '队列 ' + (summary.queued_job_count || 0),
  ].filter(Boolean).join(' · ');
  updateFeedRefreshButtons();

  document.getElementById('subscriptionConsole').innerHTML = [
    renderFeedScheduleCard(feedSchedule),
    renderSourceHealthSummary(sourceHealth),
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>公共源市场</h3><span>' + sources.length + ' 个可见源</span></div>',
    sources.length ? '<div class="subscription-card-grid">' + sources.map(function (source) {
      return renderSourceCard(source, subscribedBySource[source.id], sourceTypes);
    }).join('') + '</div>' : '<div class="empty">还没有公共或私有源。</div>',
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>我的订阅</h3><span>' + visibleSubscriptions.length + ' / ' + subscriptions.length + ' 个</span></div>',
    visibleSubscriptions.length ? '<div class="subscription-card-grid">' + visibleSubscriptions.map(function (subscription) {
      return renderSubscriptionCard(subscription, healthBySubscription[subscription.id]);
    }).join('') + '</div>' : '<div class="empty">当前健康筛选下没有订阅。</div>',
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>私有 RSS 源</h3><span>' + (viewer ? 'viewer 只读' : '仅自己可见') + '</span></div>',
    renderPrivateSourceForm(),
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>高级源测试</h3><span>' + sourceTypes.length + ' 种 source_type</span></div>',
    admin ? '<div class="subscription-actions"><button type="button" data-import-config-sources>导入旧配置源</button></div>' : '',
    renderAdvancedSourceForm(sourceTypes),
    '</section>',
    renderMemberManagement(members),
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>API 状态</h3><span>用户作用域 Feed / 历史</span></div>',
    renderApiStatus(apiStatus, summary),
    '</section>',
    '<section class="subscription-section">',
    '  <div class="subscription-section-head"><h3>任务队列</h3><span>' + jobs.length + ' 条最近任务</span></div>',
    renderJobs(jobs),
    '</section>',
  ].join('');
}

async function subscribeToSource(sourceId) {
  if (!sourceId) return;
  setSubscriptionMessage('正在订阅...', '');
  try {
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(sourceId) + '/subscribe', {
      method: 'POST',
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('订阅已更新。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('订阅失败：' + err.message, 'error');
  }
}

async function unsubscribeFromSource(sourceId) {
  if (!sourceId) return;
  setSubscriptionMessage('正在取消订阅...', '');
  try {
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(sourceId) + '/subscription', {
      method: 'DELETE',
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('已取消订阅。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('取消订阅失败：' + err.message, 'error');
  }
}

async function toggleSubscription(subscriptionId, enabled) {
  if (!subscriptionId) return;
  setSubscriptionMessage('正在更新订阅...', '');
  try {
    await fetchSubscriptionApi('/api/me/subscriptions/' + encodeURIComponent(subscriptionId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !!enabled }),
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('订阅状态已更新。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('更新订阅失败：' + err.message, 'error');
  }
}

async function queueSourceJob(sourceId, kind, subscriptionId) {
  if (!sourceId) return;
  if (!beginJobSubmission(kind, sourceId, subscriptionId)) return;
  var actionContext = captureSubscriptionAction();
  var endpoint = kind === 'source_fetch' ? '/api/jobs/source-fetch' : '/api/jobs/source-test';
  var requestBody = {
    source_id: sourceId,
    payload: { reason: 'subscription_console' },
  };
  if (subscriptionId) requestBody.subscription_id = subscriptionId;
  setSubscriptionMessage('正在创建任务...', '');
  try {
    var job = await fetchSubscriptionApi(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });
    if (!subscriptionActionIsCurrent(actionContext)) return;
    setSubscriptionMessage('任务已排队：' + job.id, '');
    pollJobUntilTerminal(
      job.id,
      job.job_type || kind,
      Date.now(),
      job.source_id || sourceId,
      job.subscription_id || subscriptionId
    );
    await loadJobsPreview();
  } catch (err) {
    if (subscriptionActionIsCurrent(actionContext)) {
      setSubscriptionMessage('创建任务失败：' + err.message, 'error');
    }
  } finally {
    if (subscriptionActionIsCurrent(actionContext)) endJobSubmission();
  }
}

async function refreshMyFeed() {
  if (!beginJobSubmission('user_feed_refresh')) return;
  var actionContext = captureSubscriptionAction();
  setSubscriptionMessage('正在创建刷新任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/user-feed-refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: { reason: 'manual_subscription_console' } }),
    });
    if (!subscriptionActionIsCurrent(actionContext)) return;
    var workerStatus = (state.feedSchedule && state.feedSchedule.worker_status) ||
      ((((state.subscriptionConsole || {}).summary || {}).runtime || {}).worker_status);
    if (typeof setFeedActivity === 'function') {
      setFeedActivity(job, { workerStatus: workerStatus || 'unknown' });
    }
    setSubscriptionMessage(
      job.deduplicated
        ? '已有刷新任务，继续等待：' + job.id
        : (workerStatus === 'missing' || workerStatus === 'stale'
        ? '任务已排队但暂不会执行：Worker ' + workerStatus
        : '任务已排队：' + job.id),
      workerStatus === 'missing' || workerStatus === 'stale' ? 'error' : ''
    );
    pollJobUntilTerminal(job.id, job.job_type || 'user_feed_refresh', Date.now());
    await loadJobsPreview();
  } catch (err) {
    if (subscriptionActionIsCurrent(actionContext)) {
      setSubscriptionMessage('刷新任务失败：' + err.message, 'error');
    }
  } finally {
    if (subscriptionActionIsCurrent(actionContext)) endJobSubmission();
  }
}

function setSubscriptionJobPoll(jobId, jobType, startedAt, sourceId, subscriptionId) {
  state.subscriptionJobPollGeneration = (state.subscriptionJobPollGeneration || 0) + 1;
  state.subscriptionJobPoll = jobId ? {
    jobId: jobId,
    jobType: jobType || '',
    sourceId: sourceId || null,
    subscriptionId: subscriptionId || null,
    startedAt: startedAt || Date.now(),
    consecutiveFailures: 0,
    timer: null,
    generation: state.subscriptionJobPollGeneration,
    userId: currentFeedScheduleWatchUserId(),
  } : null;
  if (state.subscriptionConsole) renderSubscriptionConsole(state.subscriptionConsole);
  updateFeedRefreshButtons();
}

function cancelSubscriptionJobPoll() {
  var active = state.subscriptionJobPoll;
  if (active && active.timer) window.clearTimeout(active.timer);
  state.subscriptionJobPollGeneration = (state.subscriptionJobPollGeneration || 0) + 1;
  state.subscriptionJobPoll = null;
  if (state.subscriptionConsole) renderSubscriptionConsole(state.subscriptionConsole);
  updateFeedRefreshButtons();
}

function finishSubscriptionJobPoll(message, type) {
  cancelSubscriptionJobPoll();
  if (message) setSubscriptionMessage(message, type || '');
}

function subscriptionJobPollIsCurrent(jobId, generation, userId) {
  var active = state.subscriptionJobPoll;
  return !!active &&
    active.jobId === jobId &&
    active.generation === generation &&
    active.userId === userId &&
    currentFeedScheduleWatchUserId() === userId;
}

function pollJobUntilTerminal(jobId, jobType, startedAt, sourceId, subscriptionId) {
  if (!jobId) return Promise.resolve(null);
  if (state.subscriptionJobPoll && state.subscriptionJobPoll.jobId === jobId) {
    return Promise.resolve(null);
  }
  setSubscriptionJobPoll(jobId, jobType, startedAt, sourceId, subscriptionId);
  var pollGeneration = state.subscriptionJobPoll.generation;
  var pollUserId = state.subscriptionJobPoll.userId;

  return new Promise(function (resolve) {
    async function poll() {
      var active = state.subscriptionJobPoll;
      if (!subscriptionJobPollIsCurrent(jobId, pollGeneration, pollUserId)) {
        resolve(null);
        return;
      }
      if (Date.now() - active.startedAt >= 180000) {
        finishSubscriptionJobPoll('任务仍在后台运行，可稍后在任务队列查看。', 'error');
        resolve(null);
        return;
      }
      try {
        var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '?ts=' + Date.now());
        if (!subscriptionJobPollIsCurrent(jobId, pollGeneration, pollUserId)) {
          resolve(null);
          return;
        }
        active = state.subscriptionJobPoll;
        if (typeof setFeedActivity === 'function') {
          setFeedActivity(job, {
            workerStatus: (state.feedSchedule && state.feedSchedule.worker_status) || 'unknown',
          });
        }
        active.sourceId = active.sourceId || job.source_id || null;
        active.subscriptionId = active.subscriptionId || job.subscription_id || null;
        active.consecutiveFailures = 0;
        await loadJobsPreview();
        if (!subscriptionJobPollIsCurrent(jobId, pollGeneration, pollUserId)) {
          resolve(null);
          return;
        }
        if (['succeeded', 'partial', 'failed', 'cancelled'].indexOf(job.status) >= 0) {
          var result = job.result_json || {};
          var isCurrent = function () {
            return subscriptionJobPollIsCurrent(jobId, pollGeneration, pollUserId);
          };
          await loadFeedSchedule({
            silent: true,
            render: false,
            resume: false,
            isCurrent: isCurrent,
          });
          if (!isCurrent()) {
            resolve(null);
            return;
          }
          await refreshSourceHealthForTerminalJob(job, isCurrent);
          if (!isCurrent()) {
            resolve(null);
            return;
          }
          if (result.snapshot_id && !feedTerminalJobHandled(job.id)) {
            await reloadFeedForTerminalJob(job, isCurrent, true);
            if (!isCurrent()) {
              resolve(null);
              return;
            }
          }
          reconcileTerminalJobCaches(job);
          if (job.status === 'succeeded') {
            finishSubscriptionJobPoll('任务已完成：' + job.id, '');
          } else if (job.status === 'partial') {
            finishSubscriptionJobPoll('任务部分完成：' + (jobErrorText(job) || job.id), 'error');
          } else {
            finishSubscriptionJobPoll(
              '任务' + (job.status === 'cancelled' ? '已取消' : '失败') + '：' +
                (jobErrorText(job) || job.id),
              'error'
            );
          }
          resumeNextActiveSubscriptionJobPoll(job.id);
          resolve(job);
          return;
        }
      } catch (err) {
        if (!subscriptionJobPollIsCurrent(jobId, pollGeneration, pollUserId)) {
          resolve(null);
          return;
        }
        active = state.subscriptionJobPoll;
        active.consecutiveFailures += 1;
        if (active.consecutiveFailures >= 3) {
          finishSubscriptionJobPoll('任务状态读取失败：' + err.message, 'error');
          resolve(null);
          return;
        }
      }
      if (!subscriptionJobPollIsCurrent(jobId, pollGeneration, pollUserId)) {
        resolve(null);
        return;
      }
      active = state.subscriptionJobPoll;
      active.timer = window.setTimeout(poll, 2000);
    }
    poll();
  });
}

function resumeActiveFeedJobPoll(jobs) {
  if (state.subscriptionJobSubmission || state.subscriptionJobPoll) return;
  var supportedTypes = ['user_feed_refresh', 'source_fetch', 'source_test'];
  var currentUserId = state.auth.user && state.auth.user.id;
  var active = (jobs || []).filter(function (job) {
    var ownedByCurrentUser = !currentUserId || job.user_id === currentUserId;
    return ownedByCurrentUser &&
      supportedTypes.indexOf(job.job_type) >= 0 &&
      ['queued', 'running'].indexOf(job.status) >= 0;
  }).sort(function (left, right) {
    return (Date.parse(right.created_at) || 0) - (Date.parse(left.created_at) || 0);
  })[0];
  if (active) {
    pollJobUntilTerminal(
      active.id,
      active.job_type,
      Date.now(),
      active.source_id,
      active.subscription_id
    );
  }
}

function reconcileTerminalJobCaches(job) {
  if (!job || !job.id) return;
  if (state.feedSchedule && state.feedSchedule.active_job &&
      state.feedSchedule.active_job.id === job.id) {
    state.feedSchedule.active_job = null;
  }
  if (state.subscriptionConsole) {
    state.subscriptionConsole.jobs = (state.subscriptionConsole.jobs || []).map(function (cached) {
      return cached.id === job.id ? Object.assign({}, cached, job) : cached;
    });
    if (state.subscriptionConsole.feedSchedule &&
        state.subscriptionConsole.feedSchedule.active_job &&
        state.subscriptionConsole.feedSchedule.active_job.id === job.id) {
      state.subscriptionConsole.feedSchedule.active_job = null;
    }
  }
}

function resumeNextActiveSubscriptionJobPoll(completedJobId) {
  var remaining = currentUserActiveSubscriptionJobs().filter(function (job) {
    return job.id !== completedJobId;
  });
  resumeActiveFeedJobPoll(remaining);
}

async function loadJobsPreview() {
  var loadToken = Number(state.subscriptionConsoleLoadToken || 0);
  var loadUserId = currentFeedScheduleWatchUserId();
  try {
    var data = await fetchSubscriptionApi('/api/jobs?limit=20&ts=' + Date.now());
    if (!subscriptionConsoleGenerationIsCurrent(loadToken, loadUserId)) return null;
    state.subscriptionConsole = state.subscriptionConsole || {};
    state.subscriptionConsole.jobs = data.jobs || [];
    renderSubscriptionConsole(state.subscriptionConsole);
    return data;
  } catch (err) {
    if (!subscriptionConsoleGenerationIsCurrent(loadToken, loadUserId)) return null;
    setSubscriptionMessage('任务列表读取失败：' + err.message, 'error');
    return null;
  }
}

async function showHealthJob(jobId) {
  if (!jobId) return;
  var actionContext = captureSubscriptionAction();
  var consoleData = state.subscriptionConsole || {};
  var jobs = (consoleData.jobs || []).slice();
  var job = jobs.find(function (candidate) { return candidate.id === jobId; });
  try {
    if (!job) {
      job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '?ts=' + Date.now());
      if (!subscriptionActionIsCurrent(actionContext)) return;
    }
    if (!subscriptionActionIsCurrent(actionContext)) return;
    consoleData.jobs = [job].concat(jobs.filter(function (candidate) {
      return candidate.id !== jobId;
    }));
    state.subscriptionConsole = consoleData;
    renderSubscriptionConsole(consoleData);
    setSubscriptionMessage('已定位最近任务：' + jobId, '');
    window.setTimeout(function () {
      if (!subscriptionActionIsCurrent(actionContext)) return;
      var row = Array.prototype.find.call(
        document.querySelectorAll('[data-job-id]'),
        function (candidate) { return candidate.getAttribute('data-job-id') === jobId; }
      );
      if (row && row.scrollIntoView) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 0);
  } catch (err) {
    if (subscriptionActionIsCurrent(actionContext)) {
      setSubscriptionMessage('最近任务读取失败：' + err.message, 'error');
    }
  }
}

async function cancelJob(jobId) {
  if (!jobId) return;
  setSubscriptionMessage('正在取消任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '/cancel', {
      method: 'POST',
    });
    setSubscriptionMessage('任务已取消：' + job.id, '');
    await loadJobsPreview();
  } catch (err) {
    setSubscriptionMessage('取消任务失败：' + err.message, 'error');
  }
}

async function retryJob(jobId, fallbackJob) {
  if (!jobId) return;
  var previous = (((state.subscriptionConsole || {}).jobs) || []).find(function (job) {
    return job.id === jobId;
  }) || fallbackJob || {};
  if (!beginJobSubmission(previous.job_type, previous.source_id, previous.subscription_id)) return;
  var actionContext = captureSubscriptionAction();
  setSubscriptionMessage('正在重试任务...', '');
  try {
    var job = await fetchSubscriptionApi('/api/jobs/' + encodeURIComponent(jobId) + '/retry', {
      method: 'POST',
    });
    if (!subscriptionActionIsCurrent(actionContext)) return;
    if (typeof setFeedActivity === 'function') {
      setFeedActivity(job, {
        workerStatus: (state.feedSchedule && state.feedSchedule.worker_status) || 'unknown',
      });
    }
    setSubscriptionMessage('任务已重新排队：' + job.id, '');
    pollJobUntilTerminal(
      job.id,
      job.job_type || previous.job_type || '',
      Date.now(),
      job.source_id || previous.source_id,
      job.subscription_id || previous.subscription_id
    );
    await loadJobsPreview();
  } catch (err) {
    if (subscriptionActionIsCurrent(actionContext)) {
      setSubscriptionMessage('重试任务失败：' + err.message, 'error');
    }
  } finally {
    if (subscriptionActionIsCurrent(actionContext)) endJobSubmission();
  }
}

async function createPrivateSource(event) {
  event.preventDefault();
  var form = event.target.closest('form');
  if (!form) return;
  var topics = Array.from(form.querySelectorAll('input[name="default_topics"]:checked')).map(function (item) {
    return item.value;
  });
  var payload = {
    scope: "private",
    type: 'rss',
    display_name: form.elements.display_name.value.trim(),
    default_channel: form.elements.default_channel.value,
    default_topics: topics,
    config: {
      name: form.elements.display_name.value.trim(),
      url: form.elements.feed_url.value.trim(),
    },
    enabled: true,
  };
  setSubscriptionMessage('正在创建私有源...', '');
  try {
    var source = await fetchSubscriptionApi('/api/catalog/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(source.id) + '/subscribe', {
      method: 'POST',
    });
    form.reset();
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('私有源已创建并订阅。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('创建私有源失败：' + err.message, 'error');
  }
}

async function createAdvancedSource(event) {
  event.preventDefault();
  var form = event.target.closest('form');
  if (!form) return;
  var sourceType = form.elements.source_type.value;
  var definition = sourceTypeDefinition(sourceType, ((state.subscriptionConsole || {}).sourceTypes) || []);
  var config = {};
  try {
    config = sourceEditorPayload(form, definition).config;
  } catch (err) {
    setSubscriptionMessage('config JSON 解析失败：' + err.message, 'error');
    return;
  }
  var topics = (form.elements.default_topics.value || '')
    .split(',')
    .map(function (item) { return item.trim(); })
    .filter(Boolean);
  var payload = {
    type: sourceType,
    display_name: form.elements.display_name.value.trim() || sourceType,
    default_channel: form.elements.default_channel.value || null,
    default_topics: topics,
    config: config,
    enabled: true,
  };
  if (form.elements.secret_env) {
    payload.secret_env = form.elements.secret_env.value.trim() || null;
  }
  setSubscriptionMessage('正在创建高级源...', '');
  try {
    var source = await fetchSubscriptionApi('/api/catalog/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await fetchSubscriptionApi('/api/catalog/sources/' + encodeURIComponent(source.id) + '/subscribe', {
      method: 'POST',
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('高级源已创建并订阅。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('创建高级源失败：' + err.message, 'error');
  }
}

async function importConfigSources() {
  setSubscriptionMessage('正在导入旧配置源...', '');
  try {
    var result = await fetchSubscriptionApi('/api/catalog/import-config-sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscribe_current_user: true }),
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage(
      '导入完成：新建 ' + result.created + '，更新 ' + result.updated + '，跳过 ' + result.skipped + '。',
      result.errors && result.errors.length ? 'error' : ''
    );
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('导入失败：' + err.message, 'error');
  }
}

async function createMember(event) {
  event.preventDefault();
  if (!subscriptionUserIsAdmin()) return;
  var form = event.target.closest('form');
  if (!form) return;
  var payload = {
    username: form.elements.username.value.trim(),
    password: form.elements.password.value,
    display_name: form.elements.display_name.value.trim() || null,
    role: form.elements.role.value,
    enabled: !!form.elements.enabled.checked,
  };
  setSubscriptionMessage('正在创建成员...', '');
  try {
    await fetchSubscriptionApi('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    form.reset();
    form.elements.enabled.checked = true;
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('成员已创建。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('创建成员失败：' + err.message, 'error');
  }
}

async function updateMember(event) {
  event.preventDefault();
  if (!subscriptionUserIsAdmin()) return;
  var form = event.target.closest('[data-member-update]');
  if (!form) return;
  var memberId = form.getAttribute('data-member-update');
  var payload = {
    display_name: form.elements.display_name.value.trim() || null,
    role: form.elements.role.value,
    enabled: !!form.elements.enabled.checked,
  };
  var password = form.elements.password.value.trim();
  if (password) {
    payload.password = password;
  }
  setSubscriptionMessage('正在更新成员...', '');
  try {
    await fetchSubscriptionApi('/api/users/' + encodeURIComponent(memberId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.subscriptionConsoleLoaded = false;
    setSubscriptionMessage('成员已更新。', '');
    await loadSubscriptionConsole();
  } catch (err) {
    setSubscriptionMessage('更新成员失败：' + err.message, 'error');
  }
}

function bindSubscriptionEvents() {
  var panel = document.getElementById('subscriptionPanel');
  if (!panel) return;
  document.getElementById('reloadSubscriptionsBtn').addEventListener('click', function () {
    state.subscriptionConsoleLoaded = false;
    loadSubscriptionConsole();
  });
  document.getElementById('refreshMyFeedBtn').addEventListener('click', refreshMyFeed);
  panel.addEventListener('submit', function (event) {
    var sourceEditor = event.target && event.target.closest('[data-source-editor]');
    if (sourceEditor) {
      event.preventDefault();
      saveSourceEditor(sourceEditor, editorAction(event));
      return;
    }
    var subscriptionEditor = event.target && event.target.closest('[data-subscription-editor]');
    if (subscriptionEditor) {
      event.preventDefault();
      saveSubscriptionEditor(subscriptionEditor, editorAction(event));
      return;
    }
    if (event.target && event.target.id === 'feedScheduleForm') {
      saveFeedSchedule(event);
      return;
    }
    if (event.target && event.target.id === 'privateSourceForm') {
      createPrivateSource(event);
    }
    if (event.target && event.target.id === 'advancedSourceForm') {
      createAdvancedSource(event);
      return;
    }
    if (event.target && event.target.id === 'memberManagementForm') {
      createMember(event);
      return;
    }
    if (event.target && event.target.closest('[data-member-update]')) {
      updateMember(event);
    }
  });
  panel.addEventListener('change', function (event) {
    if (event.target && event.target.name === 'source_type' && event.target.closest('#advancedSourceForm')) {
      updateAdvancedSourceFields(event.target.closest('#advancedSourceForm'), event.target.value);
    }
  });
  panel.addEventListener('click', function (event) {
    var healthFilter = event.target.closest('[data-source-health-filter]');
    if (healthFilter) {
      setSourceHealthFilter(healthFilter.getAttribute('data-source-health-filter') || '');
      return;
    }
    var healthJob = event.target.closest('[data-health-job]');
    if (healthJob) {
      showHealthJob(healthJob.getAttribute('data-health-job'));
      return;
    }
    var importButton = event.target.closest('[data-import-config-sources]');
    if (importButton) {
      importConfigSources();
      return;
    }
    var subscribeButton = event.target.closest('[data-subscribe-source]');
    if (subscribeButton) {
      subscribeToSource(subscribeButton.getAttribute('data-subscribe-source'));
      return;
    }
    var unsubscribeButton = event.target.closest('[data-unsubscribe-source]');
    if (unsubscribeButton) {
      unsubscribeFromSource(unsubscribeButton.getAttribute('data-unsubscribe-source'));
      return;
    }
    var toggleButton = event.target.closest('[data-toggle-subscription]');
    if (toggleButton) {
      toggleSubscription(
        toggleButton.getAttribute('data-toggle-subscription'),
        toggleButton.getAttribute('data-enabled') === '1'
      );
      return;
    }
    var testButton = event.target.closest('[data-source-test]');
    if (testButton) {
      queueSourceJob(
        testButton.getAttribute('data-source-test'),
        'source_test',
        testButton.getAttribute('data-subscription-id')
      );
      return;
    }
    var fetchButton = event.target.closest('[data-source-fetch]');
    if (fetchButton) {
      queueSourceJob(
        fetchButton.getAttribute('data-source-fetch'),
        'source_fetch',
        fetchButton.getAttribute('data-subscription-id')
      );
      return;
    }
    var cancelButton = event.target.closest('[data-cancel-job]');
    if (cancelButton) {
      cancelJob(cancelButton.getAttribute('data-cancel-job'));
      return;
    }
    var retryButton = event.target.closest('[data-retry-job]');
    if (retryButton) {
      retryJob(retryButton.getAttribute('data-retry-job'));
    }
  });
}
