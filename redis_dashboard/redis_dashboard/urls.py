from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

from cpuprofile import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('captures/new', views.new_capture, name='new_capture'),
    path('captures/<int:pk>/', views.capture_detail, name='capture'),
    path('captures/<int:pk>/live', views.capture_live, name='capture_live'),
    path('captures/<int:pk>/samples/<int:index>/', views.sample_detail, name='sample'),
    path('captures/<int:pk>/stop', views.stop_capture, name='stop_capture'),
    path('captures/<int:pk>/delete', views.delete_capture, name='delete_capture'),
    # old bookmarks
    path('traces/', RedirectView.as_view(pattern_name='home')),
    path('capturecommandstosql', RedirectView.as_view(pattern_name='home')),
]
