{
    "name": "Generic Data Sync",
    "version": "19.0.1.0.0",
    "summary": "Generic, dynamic, model-agnostic data sync with scheduling",
    "author": "MeruCore Solutions",
    "website": "https://merucore.com",
    "license": "LGPL-3",
    "depends": ["base", "sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/generic_sync_backend_views.xml",
        "views/generic_sync_job_views.xml",
        "data/generic_sync_cron.xml",
    ],
    "application": False,
    "installable": True,
}
