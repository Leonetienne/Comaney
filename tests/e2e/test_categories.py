"""Category and tag CRUD, including rename via inline editor."""
import time

import pytest
from selenium.webdriver.common.by import By

from helpers import _url, setup_user, cleanup_user


@pytest.fixture(scope="module")
def ctx(driver, w):
    c = setup_user(driver, w)
    yield c
    cleanup_user(c["email"])


class TestCategories:

    def test_create_category(self, driver, w, ctx):
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert "/budget/" in driver.current_url, \
            f"Expected categories page, got {driver.current_url}"
        driver.execute_script(
            "var inp = document.getElementById('category-input');"
            "inp.value = 'My Category';"
            "inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));")
        time.sleep(1)
        assert "My Category" in driver.find_element(By.ID, "category-list").text

    def test_rename_category(self, driver, w, ctx):
        ctx["cat_uid"] = driver.execute_script(
            "return document.querySelector('#category-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#category-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        time.sleep(0.5)
        driver.execute_script(
            "var inp=document.querySelector('#category-list .ct-name-input');"
            "inp.value='Renamed Category';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert "Renamed Category" in driver.page_source

    def test_create_tag(self, driver, w, ctx):
        driver.execute_script(
            "var inp = document.getElementById('tag-input');"
            "inp.value = 'My Tag';"
            "inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));")
        time.sleep(1)
        assert "My Tag" in driver.find_element(By.ID, "tag-list").text

    def test_rename_tag(self, driver, w, ctx):
        ctx["tag_uid"] = driver.execute_script(
            "return document.querySelector('#tag-list .ct-name').dataset.uid;")
        driver.execute_script(
            "var el=document.querySelector('#tag-list .ct-name');"
            "el.scrollIntoView({block:'center'}); el.click();")
        time.sleep(0.5)
        driver.execute_script(
            "var inp=document.querySelector('#tag-list .ct-name-input');"
            "inp.value='Renamed Tag';"
            "inp.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));")
        time.sleep(0.5)
        driver.get(_url("/budget/categories-tags/"))
        time.sleep(1)
        assert "Renamed Tag" in driver.page_source

    def test_delete_category(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, f"#category-{ctx['cat_uid']} .ct-delete").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert f"category-{ctx['cat_uid']}" not in driver.page_source

    def test_delete_tag(self, driver, w, ctx):
        driver.find_element(By.CSS_SELECTOR, f"#tag-{ctx['tag_uid']} .ct-delete").click()
        time.sleep(0.5)
        driver.find_element(By.ID, "cdialog-ok").click()
        time.sleep(1)
        assert f"tag-{ctx['tag_uid']}" not in driver.page_source
