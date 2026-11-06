sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/16/main/postgresql.conf
echo "host all all 0.0.0.0/0 md5" >> /etc/postgresql/16/main/pg_hba.conf
echo "host all all ::0/0 md5" >> /etc/postgresql/16/main/pg_hba.conf
systemctl restart postgresql
su - postgres -c "psql -c \"ALTER USER postgres WITH PASSWORD 'postgres_password_123';\""
su - postgres -c "psql -c \"CREATE DATABASE energy_monitoring;\"" || true

