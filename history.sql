--
-- PostgreSQL database dump
--

-- Dumped from database version 13.2
-- Dumped by pg_dump version 13.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: document_type; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.document_type AS ENUM (
    'document',
    'photo',
    'video',
    'animation',
    'voice'
);


ALTER TYPE public.document_type OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: deleted_message; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.deleted_message (
    entry_id integer NOT NULL,
    chat_id bigint NOT NULL,
    message_id integer NOT NULL
);


ALTER TABLE public.deleted_message OWNER TO postgres;

--
-- Name: deleted_message_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.deleted_message_entry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.deleted_message_entry_id_seq OWNER TO postgres;

--
-- Name: deleted_message_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.deleted_message_entry_id_seq OWNED BY public.deleted_message.entry_id;


--
-- Name: document_index; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.document_index (
    chat_id bigint NOT NULL,
    from_user bigint NOT NULL,
    forward_from bigint,
    message_id integer NOT NULL,
    body text,
    doc_type public.document_type NOT NULL,
    file_id character varying(120) NOT NULL,
    message_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.document_index OWNER TO postgres;

--
-- Name: edit_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.edit_history (
    entry_id integer NOT NULL,
    chat_id bigint NOT NULL,
    from_user bigint NOT NULL,
    message_id integer NOT NULL,
    body text,
    edit_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.edit_history OWNER TO postgres;

--
-- Name: edit_history_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.edit_history_entry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.edit_history_entry_id_seq OWNER TO postgres;

--
-- Name: edit_history_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.edit_history_entry_id_seq OWNED BY public.edit_history.entry_id;


--
-- Name: group_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.group_history (
    chat_id bigint NOT NULL,
    user_id integer NOT NULL,
    message_id integer NOT NULL,
    history_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.group_history OWNER TO postgres;

--
-- Name: message_index; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.message_index (
    chat_id bigint NOT NULL,
    message_id integer NOT NULL,
    from_user bigint,
    forward_from bigint,
    body text NOT NULL,
    message_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.message_index OWNER TO postgres;

--
-- Name: online_record; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.online_record (
    user_id integer NOT NULL,
    entry_date timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    is_offline boolean DEFAULT false NOT NULL
);


ALTER TABLE public.online_record OWNER TO postgres;

--
-- Name: user_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_history (
    entry_id integer NOT NULL,
    user_id bigint NOT NULL,
    first_name character varying(256) NOT NULL,
    last_name character varying(256) DEFAULT NULL::character varying,
    full_name character varying(513) DEFAULT ''::character varying NOT NULL,
    photo_id character varying(80) DEFAULT NULL::character varying NOT NULL,
    last_update timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.user_history OWNER TO postgres;

--
-- Name: COLUMN user_history.photo_id; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON COLUMN public.user_history.photo_id IS 'big_file_id';


--
-- Name: user_history_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.user_history_entry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.user_history_entry_id_seq OWNER TO postgres;

--
-- Name: user_history_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.user_history_entry_id_seq OWNED BY public.user_history.entry_id;


--
-- Name: user_index; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_index (
    user_id bigint NOT NULL,
    peer_id bigint,
    last_refresh timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    update_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    first_name character varying(256) NOT NULL,
    last_name character varying(256) DEFAULT NULL::character varying,
    is_group boolean DEFAULT false NOT NULL,
    is_bot boolean DEFAULT false NOT NULL,
    photo_id character varying(80) DEFAULT NULL::character varying,
    hash character varying(64) NOT NULL
);


ALTER TABLE public.user_index OWNER TO postgres;

--
-- Name: username_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.username_history (
    entry_id integer NOT NULL,
    user_id bigint NOT NULL,
    username character varying(32) NOT NULL,
    update_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.username_history OWNER TO postgres;

--
-- Name: username_history_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.username_history_entry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.username_history_entry_id_seq OWNER TO postgres;

--
-- Name: username_history_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.username_history_entry_id_seq OWNED BY public.username_history.entry_id;


--
-- Name: deleted_message entry_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deleted_message ALTER COLUMN entry_id SET DEFAULT nextval('public.deleted_message_entry_id_seq'::regclass);


--
-- Name: edit_history entry_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.edit_history ALTER COLUMN entry_id SET DEFAULT nextval('public.edit_history_entry_id_seq'::regclass);


--
-- Name: user_history entry_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_history ALTER COLUMN entry_id SET DEFAULT nextval('public.user_history_entry_id_seq'::regclass);


--
-- Name: username_history entry_id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.username_history ALTER COLUMN entry_id SET DEFAULT nextval('public.username_history_entry_id_seq'::regclass);


--
-- Name: deleted_message deleted_message_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.deleted_message
    ADD CONSTRAINT deleted_message_pk PRIMARY KEY (entry_id);


--
-- Name: document_index document_index_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.document_index
    ADD CONSTRAINT document_index_pk PRIMARY KEY (chat_id, message_id);


--
-- Name: edit_history edit_history_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.edit_history
    ADD CONSTRAINT edit_history_pk PRIMARY KEY (entry_id);


--
-- Name: group_history group_history_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.group_history
    ADD CONSTRAINT group_history_pk PRIMARY KEY (chat_id, message_id);


--
-- Name: message_index message_index_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.message_index
    ADD CONSTRAINT message_index_pk PRIMARY KEY (chat_id, message_id);


--
-- Name: user_history user_history_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_history
    ADD CONSTRAINT user_history_pk PRIMARY KEY (entry_id);


--
-- Name: user_index user_index_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_index
    ADD CONSTRAINT user_index_pk PRIMARY KEY (user_id);


--
-- Name: username_history username_history_pk; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.username_history
    ADD CONSTRAINT username_history_pk PRIMARY KEY (entry_id);


--
-- PostgreSQL database dump complete
--
