{
    'name': 'Agriculture Farm Management - Crop Planning, Livestock, Dairy, Poultry, Farm Job Costing',
    'summary': 'Agriculture management and farm management ERP: crop management, crop planning, crop scouting, '
               'farm job costing with job cost sheet and cost per hectare, field mapping, farm weather records '
               'with alerts, harvest lots and crop yield analysis, livestock management, dairy farm milk yield, '
               'poultry farm egg production, vaccination, contract farming crop request portal',
    'description': 'One module for a farm business: farms and fields on a map, crop plans per season, '
                   'field activities that use stock, labour and machinery, a job cost sheet with budget versus '
                   'actual, crop scouting, Open-Meteo weather with alerts, harvest lots sold through sales orders, '
                   'dairy cattle, poultry flocks, goats and sheep, and a crop request portal.',
    'version': '19.0.1.0.1',
    'category': 'Industries',
    'author': 'Modvanta',
    'maintainer': 'Modvanta',
    'website': '',
    'support': 'modvantaapps@gmail.com',
    'license': 'OPL-1',
    'price': 40.0,
    'currency': 'USD',
    'depends': [
        'web',
        'mail',
        'portal',
        'website',
        'stock',
        'sale_management',
        'sale_stock',
        'purchase',
        'account',
        'hr',
        'hr_hourly_cost',
        'maintenance',
    ],
    'data': [
        'security/agriculture_security.xml',
        'security/ir.model.access.csv',
        'data/agriculture_data.xml',
        'views/farm_views.xml',
        'views/crop_views.xml',
        'views/crop_plan_views.xml',
        'views/activity_views.xml',
        'views/harvest_views.xml',
        'views/scouting_weather_views.xml',
        'views/livestock_views.xml',
        'views/request_settings_views.xml',
        'views/portal_templates.xml',
        'report/agriculture_reports.xml',
    ],
    'demo': [
        'demo/agriculture_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mdv_agriculture_suite/static/src/js/dashboard.js',
            'mdv_agriculture_suite/static/src/js/map_field.js',
            'mdv_agriculture_suite/static/src/js/livestock_scan.js',
            'mdv_agriculture_suite/static/src/xml/*.xml',
            'mdv_agriculture_suite/static/src/scss/*.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
