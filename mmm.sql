create database if not exists
lab char set utf8mb3;
collate uff8_unicode_ci;

use lab;
create table if not exists vendor(
v_code integer,
v_company varchar(100),
c_inname char(12) unique,
v_address varchar(255),
primary key(v_code)
);