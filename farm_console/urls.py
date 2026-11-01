from django.urls import path

from farm_console.views import (
    account_page,
    accounts_page,
    errors_page,
    farm_home,
    filters_page,
    folder_create,
    folder_page,
    import_page,
    login_view,
    logout_view,
    pc_page,
    sbc_week_page,
    schedule_page,
)

urlpatterns = [
    path('login/', login_view, name='farm-login'),
    path('logout/', logout_view, name='farm-logout'),
    path('', farm_home, name='farm-home'),
    path('folders/new/', folder_create, name='farm-folder-create'),
    path('folders/<int:folder_id>/', folder_page, name='farm-folder'),
    path('schedule/', schedule_page, name='farm-schedule'),
    path('pc/', pc_page, name='farm-pc'),
    path('accounts/', accounts_page, name='farm-accounts'),
    path('accounts/<int:account_id>/', account_page, name='farm-account'),
    path('filters/', filters_page, name='farm-filters'),
    path('sbc/', sbc_week_page, name='farm-sbc-week'),
    path('errors/', errors_page, name='farm-errors'),
    path('import/', import_page, name='farm-import'),
]
