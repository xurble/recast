


#DO NOT CHECK THIS IN!!!!!!!!!


import os

SITE_ROOT = os.path.dirname(os.path.realpath(__file__))

paths = SITE_ROOT.split(os.sep)
INSTALL_LOCATION = paths[len(paths)-2]  
print INSTALL_LOCATION


if INSTALL_LOCATION == "Dropbox":

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3', # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
            'NAME': os.path.join(SITE_ROOT,'../../recast.sqlite'),                      # Or path to database file if using sqlite3.
            'USER': '',                      # Not used with sqlite3.
            'PASSWORD': '',                  # Not used with sqlite3.
            'HOST': '',                      # Set to empty string for localhost. Not used with sqlite3.
            'PORT': '',                      # Set to empty string for default. Not used with sqlite3.
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql', # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
            'NAME': 'cruisem1_recast',                      # Or path to database file if using sqlite3.
            'USER': 'cruisem1_recast',                      # Not used with sqlite3.
            'PASSWORD': 'r3cast3r',          # Not used with sqlite3.
            'HOST': '',                      # Set to empty string for localhost. Not used with sqlite3.
            'PORT': '',                      # Set to empty string for default. Not used with sqlite3.
        }
    }



# Make this unique, and don't share it with anybody.
SECRET_KEY = 'cw2n@n8=@sjdlksajd@#$)(#RIOPJLKFb2!^@5abxdn^ef'
