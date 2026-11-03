import uuid

from django.db import models
from django.db.models import Q


class Worker(models.Model):
    worker_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=150, blank=True)
    token_hash = models.CharField(max_length=64)
    enabled = models.BooleanField(default=True)
    last_poll_at = models.DateTimeField(null=True, blank=True)
    agent_version = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return self.worker_id


class Account(models.Model):
    ea_account_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=150, blank=True)
    email = models.CharField(max_length=254, null=True, blank=True)
    ban = models.BooleanField(default=False)
    snipe_allowed = models.BooleanField(default=False)
    balance = models.IntegerField(default=0)
    our_part = models.IntegerField(default=0)
    coins_transferred = models.IntegerField(default=0)
    owner_label = models.CharField(max_length=150, blank=True)
    preview_pack_opened_at = models.DateTimeField(null=True, blank=True)
    fix_player_at = models.CharField(max_length=150, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    market_open = models.BooleanField(null=True, blank=True)
    market_seen_open = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.email or self.name or str(self.ea_account_id)


class AccountLoginSecret(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name='login_secret')
    code_reserves = models.CharField(max_length=150, blank=True)
    totp_seed = models.CharField(max_length=150, blank=True)
    ea_password = models.CharField(max_length=150, blank=True)


class DailyMetric(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='metrics')
    date = models.DateField()
    name = models.CharField(max_length=64)
    value = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['account', 'date', 'name'], name='daily_metric_unique'),
        ]


class AccountSnapshot(models.Model):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name='snapshot')
    coins = models.IntegerField(null=True, blank=True)
    packs_count = models.IntegerField(null=True, blank=True)
    market_limit = models.IntegerField(null=True, blank=True)
    market_reset_hour = models.IntegerField(null=True, blank=True)
    market_stamps = models.JSONField(default=list)
    taken_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now=True)


class SbcTemplate(models.Model):
    name = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict)
    kind = models.CharField(max_length=32, default='challenge')
    times_per_day = models.IntegerField(default=0)
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True)


class SbcSet(models.Model):
    name = models.CharField(max_length=200, unique=True)
    common = models.BooleanField(default=False)
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class SbcSetItem(models.Model):
    sbc_set = models.ForeignKey(SbcSet, on_delete=models.CASCADE, related_name='items')
    template = models.ForeignKey(SbcTemplate, on_delete=models.CASCADE, related_name='set_items')
    priority = models.BooleanField(default=False)
    position = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['sbc_set', 'template'], name='sbc_set_item_unique'),
        ]


class Folder(models.Model):
    name = models.CharField(max_length=100, unique=True)
    filter = models.JSONField(default=list)
    refresh_on_start = models.BooleanField(default=True)
    play_mode = models.CharField(max_length=50, default='SBCmode')
    modes = models.JSONField(default=list)
    modes_text = models.TextField(blank=True)
    open_at_a_time = models.IntegerField(default=1)
    sbc_set = models.ForeignKey(SbcSet, null=True, blank=True, on_delete=models.SET_NULL)
    kill_chrome_before_scheduled = models.BooleanField(default=False)
    order = models.CharField(max_length=32, default='email')
    owner = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return self.name


class SbcAssignment(models.Model):
    STATE_ACTIVE = 'active'
    STATE_FINISHED = 'finished'
    STATE_REPLACED = 'replaced'

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='sbc_assignments')
    sbc_set = models.ForeignKey(SbcSet, on_delete=models.CASCADE, related_name='assignments')
    set_version = models.IntegerField(default=1)
    run = models.ForeignKey('FolderRun', null=True, blank=True, on_delete=models.SET_NULL)
    state = models.CharField(max_length=16, default=STATE_ACTIVE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['account'],
                condition=Q(state='active'),
                name='one_active_sbc_assignment',
            ),
        ]


class SbcAttempt(models.Model):
    OUTCOME_COLLECTED = 'collected'
    OUTCOME_FAILED = 'failed'

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='sbc_attempts')
    occurred_at = models.DateTimeField()
    sbc_name = models.CharField(max_length=200)
    challenge_id = models.CharField(max_length=64, blank=True)
    priority = models.BooleanField(default=False)
    outcome = models.CharField(max_length=16)
    reason = models.CharField(max_length=200, blank=True)
    client_event_id = models.CharField(max_length=64, unique=True)
    assignment = models.ForeignKey(SbcAssignment, null=True, blank=True, on_delete=models.SET_NULL)
    template = models.ForeignKey(SbcTemplate, null=True, blank=True, on_delete=models.SET_NULL)


class MarketFilterList(models.Model):
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class MarketFilter(models.Model):
    title = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    position = models.IntegerField(default=0)
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True)


class SnipeSettingsDoc(models.Model):
    payload = models.TextField(blank=True)
    version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True)

    @classmethod
    def current(cls):
        return cls.objects.order_by('id').first()

    @classmethod
    def write(cls, payload, updated_by=''):
        doc = cls.current()
        if doc is None:
            return cls.objects.create(payload=payload, version=1, updated_by=updated_by)
        doc.payload = payload
        doc.version += 1
        doc.updated_by = updated_by
        doc.save(update_fields=['payload', 'version', 'updated_by', 'updated_at'])
        return doc


class ModeDefinition(models.Model):
    key = models.CharField(max_length=80, unique=True)
    title_ru = models.CharField(max_length=200)
    value_kind = models.CharField(max_length=16, default='none')
    min_value = models.IntegerField(null=True, blank=True)
    max_value = models.IntegerField(null=True, blank=True)


class FolderManual(models.Model):
    KIND_INCLUDE = 'include'
    KIND_EXCLUDE = 'exclude'

    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='manuals')
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    kind = models.CharField(max_length=16)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['folder', 'account'], name='folder_manual_unique'),
        ]


class FolderMember(models.Model):
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='members')
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    source = models.CharField(max_length=16)
    snapshot_at = models.DateTimeField()


class FolderWorker(models.Model):
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='workers')
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['folder', 'worker'], name='folder_worker_unique'),
        ]


class FolderRun(models.Model):
    STATE_ACTIVE = 'active'
    STATE_STOPPED = 'stopped'
    STATE_FINISHED = 'finished'

    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='runs')
    state = models.CharField(max_length=16, default=STATE_ACTIVE)
    play_mode = models.CharField(max_length=50, default='SBCmode')
    modes = models.JSONField(default=list)
    open_at_a_time = models.IntegerField(default=1)
    started_by = models.CharField(max_length=64, default='operator')
    schedule = models.ForeignKey(
        'Schedule',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='runs',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['folder'],
                condition=Q(state='active'),
                name='one_active_run_per_folder',
            ),
        ]


class RunEntry(models.Model):
    STATE_WAITING = 'waiting'
    STATE_QUEUED = 'queued'
    STATE_OPENED = 'opened'
    STATE_CLOSED = 'closed'
    STATE_FAILED = 'failed'
    STATE_CANCELLED = 'cancelled'
    STATE_EXTRA = 'extra'

    run = models.ForeignKey(FolderRun, on_delete=models.CASCADE, related_name='entries')
    email = models.CharField(max_length=254)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    position = models.IntegerField(default=0)
    state = models.CharField(max_length=16, default=STATE_WAITING)
    queued_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    last_command = models.ForeignKey(
        'AgentCommand',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    error_text = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['run', 'email'], name='run_entry_email_unique'),
            models.UniqueConstraint(
                fields=['account'],
                condition=Q(
                    account__isnull=False,
                    state__in=['waiting', 'queued', 'opened'],
                ),
                name='one_active_run_entry_per_account',
            ),
        ]


class AgentCommand(models.Model):
    ACTION_OPEN = 'open'
    ACTION_STOP = 'stop_chrome'
    ACTION_CLOSE = 'close'

    STATE_PENDING = 'pending'
    STATE_ACKED = 'acked'
    STATE_OPENED = 'opened'
    STATE_FAILED = 'failed'
    STATE_CANCELLED = 'cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='commands')
    run = models.ForeignKey(FolderRun, null=True, blank=True, on_delete=models.SET_NULL)
    entry = models.ForeignKey(RunEntry, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=32)
    email = models.CharField(max_length=254, blank=True)
    state = models.CharField(max_length=16, default=STATE_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_text = models.CharField(max_length=300, blank=True)


class Schedule(models.Model):
    ACTION_START = 'start'
    ACTION_CONTINUE = 'continue'

    name = models.CharField(max_length=100)
    folder = models.ForeignKey(Folder, on_delete=models.CASCADE, related_name='schedules')
    action = models.CharField(max_length=16, default=ACTION_START)
    days = models.JSONField(default=list)
    start_time = models.TimeField()
    stop_time = models.TimeField()
    enabled = models.BooleanField(default=True)
    kill_chrome_before = models.BooleanField(default=True)
    assign_sbc = models.BooleanField(default=False)
    open_rule = models.CharField(max_length=32, default='all')


class ScheduleFire(models.Model):
    KIND_START = 'start'
    KIND_STOP = 'stop'

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name='fires')
    local_date = models.DateField()
    kind = models.CharField(max_length=16)
    fired_at = models.DateTimeField(auto_now_add=True)
    result = models.CharField(max_length=32)
    error = models.CharField(max_length=300, blank=True)


class NotifyOutbox(models.Model):
    STATE_PENDING = 'pending'
    STATE_SENT = 'sent'
    STATE_FAILED = 'failed'

    channel = models.CharField(max_length=32)
    text = models.TextField()
    state = models.CharField(max_length=16, default=STATE_PENDING)
    attempts = models.IntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    dedup_key = models.CharField(max_length=80, unique=True)


class ImportReport(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    source_path = models.CharField(max_length=300)
    summary = models.JSONField(default=dict)
    unresolved = models.JSONField(default=list)


class BotSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.CharField(max_length=254)
    run_entry = models.ForeignKey(RunEntry, null=True, blank=True, on_delete=models.SET_NULL)
    worker = models.ForeignKey(Worker, null=True, blank=True, on_delete=models.SET_NULL)
    client_engine = models.CharField(max_length=32, blank=True)
    client_version = models.CharField(max_length=32, blank=True)
    known_modes = models.JSONField(default=list)
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    finish_reason = models.CharField(max_length=32, blank=True)
    finish_action = models.CharField(max_length=32, blank=True)
    credentials_reads = models.IntegerField(default=0)
