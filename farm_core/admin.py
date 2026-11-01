from django.contrib import admin

from farm_core.models import Account, AccountLoginSecret, AgentCommand, Folder, Worker


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('worker_id', 'title', 'enabled', 'last_poll_at')


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'ea_account_id', 'ban')
    search_fields = ('email', 'name')


@admin.register(AccountLoginSecret)
class AccountLoginSecretAdmin(admin.ModelAdmin):
    list_display = ('account',)


@admin.register(AgentCommand)
class AgentCommandAdmin(admin.ModelAdmin):
    list_display = ('id', 'worker', 'action', 'email', 'state', 'created_at')


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ('name', 'open_at_a_time', 'play_mode')
