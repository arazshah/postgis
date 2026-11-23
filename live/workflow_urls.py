from django.urls import path

from . import workflows

urlpatterns = [
    path("<int:pk>/workflow/survey/<int:project_id>/surface/", workflows.survey_surface, name="workflow_survey_surface"),
    path("<int:pk>/workflow/plugins/", workflows.plugins_flow, name="workflow_plugins"),
    path("<int:pk>/workflow/satellite/", workflows.satellite_flow, name="workflow_satellite"),
    path("<int:pk>/workflow/survey/", workflows.survey_flow, name="workflow_survey"),
    path("<int:pk>/workflow/ows/", workflows.ows_flow, name="workflow_ows"),
    path("<int:pk>/workflow/rest/", workflows.rest_flow, name="workflow_rest"),
    path("<int:pk>/workflow/ai/", workflows.geoai, name="workflow_ai"),
    path("<int:pk>/workflow/import/", workflows.import_flow, name="workflow_import"),
    path("<int:pk>/workflow/import/<int:job_id>/", workflows.import_flow, name="workflow_import_review"),
    path("<int:pk>/api/publish/", workflows.publish_layer, name="api_publish"),
    path("<int:pk>/api/projects/", workflows.projects, name="api_projects"),
    path("<int:pk>/api/history/", workflows.history, name="api_history"),
    path("<int:pk>/<int:map_id>/source/<int:layer_id>/", workflows.source, name="api_source"),
]
