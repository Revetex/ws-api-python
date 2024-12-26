from distutils.core import setup


setup(
    name='WS-API',
    packages = ['ws_api'],
    version = '0.1.0',
    license='GPL-3.0',
    description = 'This library allows you to access your own account using the Wealthsimple (GraphQL) API using Python.',
    author = 'Guillaume Boudreau',
    author_email = 'guillaume@pommepause.com',
    url = 'https://github.com/gboudreau/ws-api-python',
    download_url = 'https://github.com/gboudreau/ws-api-python/archive/0.1.0.tar.gz',
    keywords = ['wealthsimple'],
    install_requires = [
        'requests',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: Python :: 3',
    ],
)
