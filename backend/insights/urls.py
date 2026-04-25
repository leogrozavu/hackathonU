from django.urls import path
from . import views

urlpatterns = [
    path('matches/', views.match_list),
    path('matches/<int:wy_id>/', views.match_detail),
    path('matches/<int:wy_id>/player-scores/', views.match_player_scores),
    path('matches/<int:wy_id>/ball-losses/', views.match_ball_losses),
    path('matches/<int:wy_id>/line-breaks/', views.match_line_breaks),
    path('matches/<int:wy_id>/attacking-patterns/', views.match_attacking_patterns),
    path('matches/<int:wy_id>/ai-report/', views.match_ai_report),
    path('season/summary/', views.season_summary),
    path('season/player-scores/', views.season_player_scores),
    path('season/trends/', views.season_trends),
    path('season/ball-losses/', views.season_ball_losses),
    path('season/attacking-patterns/', views.season_attacking_patterns),
    path('season/ai-trends/', views.season_ai_trends),
    path('season/coach-brief/', views.season_coach_brief),
    path('season/cross-insights/', views.season_cross_insights),
    path('ai/explain/', views.ai_explain),
    path('players/', views.players_list),
    path('players/<int:wy_id>/', views.player_detail),
    path('players/<int:wy_id>/ai-summary/', views.player_ai_summary),
    path('players/<int:wy_id>/training/', views.player_training),
    path('ai/chat/', views.ai_chat),
]
